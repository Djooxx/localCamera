import asyncio
import websockets # 确保导入
import datetime
import os
from flask import Flask, render_template, send_from_directory
import ssl
from multiprocessing import Process
import json # <--- 新增导入

# --- 配置 ---
HOST = '0.0.0.0'
HTTPS_PORT = 5001
WSS_PORT = 8766

RECORDINGS_DIR = "recordings"
# SEGMENT_DURATION_SECONDS = 60 # 服务器端分段时长，现在主要由客户端控制，这个可以作为备用或最大时长
                                # 为了演示，我们让服务器也保留一个最大分段时长，以防客户端不发信号
MAX_SEGMENT_DURATION_SECONDS = 70 # 比客户端稍长，作为客户端不发信号时的 fallback

CERT_FILE = 'server.crt'
KEY_FILE = 'server.key'
SERVER_LAN_IP = "192.168.1.3" # 请确保这是你服务器的实际局域网IP
# --- ---

app = Flask(__name__)
os.makedirs(RECORDINGS_DIR, exist_ok=True)
active_recordings = {}

@app.route('/')
def index():
    wss_address = f"wss://{SERVER_LAN_IP}:{WSS_PORT}"
    return render_template('index.html', ws_address=wss_address)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

def create_new_segment_file(client_id, remote_ip, remote_port):
    """辅助函数：关闭旧文件（如果存在）并创建新分段文件"""
    global active_recordings
    
    # 如果之前有打开的文件，关闭它
    if client_id in active_recordings and active_recordings[client_id]["file"]:
        active_recordings[client_id]["file"].close()
        print(f"客户端 {client_id}: 分段文件 {active_recordings[client_id]['path']} 已保存.")

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    client_record_dir = os.path.join(RECORDINGS_DIR, f"client_{str(remote_ip).replace('.', '_')}_{remote_port}")
    os.makedirs(client_record_dir, exist_ok=True)
    file_path_to_save = os.path.join(client_record_dir, f"video_{timestamp}.webm")
    
    current_file = open(file_path_to_save, "ab") # 追加二进制模式
    active_recordings[client_id] = {
        "file": current_file,
        "start_time": now,
        "path": file_path_to_save
    }
    print(f"客户端 {client_id}: 开始录制到新文件 {file_path_to_save}")
    return current_file


async def video_stream_handler(websocket):
    client_id = id(websocket)
    remote_ip, remote_port = ("unknown", 0)
    if websocket.remote_address:
        remote_ip, remote_port = websocket.remote_address

    request_path = websocket.request.path
    print(f"客户端 {remote_ip}:{remote_port} (请求路径: '{request_path}') 已通过WSS连接 (ID: {client_id}). 等待数据...")

    # 为新连接的客户端立即创建第一个文件
    create_new_segment_file(client_id, remote_ip, remote_port)

    try:
        async for message in websocket:
            now = datetime.datetime.now()

            if isinstance(message, str):
                try:
                    control_data = json.loads(message)
                    if control_data.get("type") == "new_segment_signal":
                        print(f"客户端 {client_id}: 收到 new_segment_signal，准备切换文件。")
                        create_new_segment_file(client_id, remote_ip, remote_port)
                    else:
                        print(f"客户端 {client_id}: 收到未知文本消息: {message}")
                except json.JSONDecodeError:
                    print(f"客户端 {client_id}: 收到无法解析的JSON文本消息: {message}")
                continue # 处理完控制消息后，跳过写入文件的步骤

            if not isinstance(message, bytes):
                print(f"客户端 {client_id}: 收到非二进制/非控制消息: {message}. 忽略.")
                continue
            
            # 服务器端的最大分段时长检查 (作为 fallback)
            # 如果客户端正常发送 new_segment_signal，这个逻辑分支一般不会在理想情况下频繁触发新文件创建
            # 但如果客户端的信号逻辑出问题或网络延迟，这个可以保证文件不会无限大
            if client_id in active_recordings and \
               (now - active_recordings[client_id]["start_time"]).total_seconds() >= MAX_SEGMENT_DURATION_SECONDS:
                print(f"客户端 {client_id}: 达到服务器最大分段时长 {MAX_SEGMENT_DURATION_SECONDS}s，强制切换文件。")
                create_new_segment_file(client_id, remote_ip, remote_port)

            # 确保文件已为写入打开 (通常在连接开始或信号触发时已打开)
            if client_id not in active_recordings or not active_recordings[client_id]["file"]:
                print(f"客户端 {client_id}: 警告 - 尝试写入数据但文件未准备好，强制创建新文件。")
                create_new_segment_file(client_id, remote_ip, remote_port)

            # 写入数据
            active_recordings[client_id]["file"].write(message)

    except websockets.exceptions.ConnectionClosedOK:
        print(f"客户端 {remote_ip}:{remote_port} (ID: {client_id}) 正常断开WSS连接.")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"客户端 {remote_ip}:{remote_port} (ID: {client_id}) 异常断开WSS连接: {e}")
    except Exception as e:
        print(f"处理客户端 {client_id} 数据时发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if client_id in active_recordings:
            if active_recordings[client_id]["file"] and not active_recordings[client_id]["file"].closed:
                active_recordings[client_id]["file"].close()
                if "path" in active_recordings[client_id]:
                     print(f"最终文件 {active_recordings[client_id]['path']} 已保存 (连接关闭).")
            del active_recordings[client_id]
        print(f"客户端 {client_id} 处理结束.")

# ... (start_websocket_server, run_flask_app, __main__ 部分基本不变, 只是注意SERVER_LAN_IP的配置) ...
async def start_websocket_server():
    """启动WebSocket Secure (WSS) 服务器"""
    ssl_context_ws = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ssl_context_ws.load_cert_chain(CERT_FILE, KEY_FILE)
    except FileNotFoundError:
        print(f"WSS错误: SSL证书 '{CERT_FILE}' 或密钥 '{KEY_FILE}' 未找到。")
        return
    except ssl.SSLError as e:
        print(f"WSS错误: 加载SSL证书/密钥时出错: {e}")
        return

    max_message_size = 10 * 1024 * 1024 

    async with websockets.serve(
        video_stream_handler,
        HOST,
        WSS_PORT,
        ssl=ssl_context_ws,
        max_size=max_message_size
    ):
        print(f"Secure WebSocket (WSS) 服务器正在监听 wss://{SERVER_LAN_IP}:{WSS_PORT} (Max message size: {max_message_size / (1024*1024):.1f} MiB)")
        await asyncio.Future()

def run_flask_app():
    """通过HTTPS运行Flask App"""
    ssl_context_flask = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ssl_context_flask.load_cert_chain(CERT_FILE, KEY_FILE)
    except FileNotFoundError:
        print(f"Flask HTTPS错误: SSL证书 '{CERT_FILE}' 或密钥 '{KEY_FILE}' 未找到。")
        return
    except ssl.SSLError as e:
        print(f"Flask HTTPS错误: 加载SSL证书/密钥时出错: {e}")
        return

    print(f"HTTPS 服务器正在监听 https://{SERVER_LAN_IP}:{HTTPS_PORT}")
    print(f"请在移动设备或PC浏览器中打开 https://{SERVER_LAN_IP}:{HTTPS_PORT}")
    # 生产环境建议关闭debug=True，并且用Gunicorn等WSGI服务器
    app.run(host=HOST, port=HTTPS_PORT, ssl_context=ssl_context_flask, debug=False) 


if __name__ == "__main__":
    # 确保 SERVER_LAN_IP 已被正确设置
    if SERVER_LAN_IP == "你的服务器局域网IP" or not SERVER_LAN_IP: # 简单检查
        print("错误: SERVER_LAN_IP 未正确设置为你的服务器在局域网中的实际IP地址。请修改 server.py 文件。")
        exit(1)
    
    print(f"服务器配置的IP地址: {SERVER_LAN_IP}")

    if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
        print(f"错误: 找不到SSL证书文件 '{CERT_FILE}' 或密钥文件 '{KEY_FILE}'.")
        print(f"请先使用OpenSSL生成它们，并将CN设置为 {SERVER_LAN_IP}")
        print(f"例如: openssl req -x509 -newkey rsa:2048 -keyout {KEY_FILE} -out {CERT_FILE} -sha256 -days 365 -nodes -subj \"/CN={SERVER_LAN_IP}\"")
        exit(1)
    print("准备启动服务...")

    flask_process = Process(target=run_flask_app)

    print("启动HTTPS服务器进程...")
    flask_process.start()

    print("启动Secure WebSocket (WSS) 服务器 (在主进程中)...")
    try:
        asyncio.run(start_websocket_server())
    except KeyboardInterrupt:
        print("服务器正在关闭 (KeyboardInterrupt)...")
    except OSError as e:
        if e.errno == 98 or e.errno == 10048: 
             print(f"错误: 端口 {WSS_PORT} (WSS) 或 {HTTPS_PORT} (HTTPS) 已被占用。")
        else:
            print(f"启动WSS服务器时发生OS错误: {e}")
    except Exception as e:
        print(f"启动WSS服务器时发生未知错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if flask_process.is_alive():
            print("正在终止HTTPS服务器进程...")
            flask_process.terminate()
            flask_process.join(timeout=5)
            if flask_process.is_alive():
                print("HTTPS服务器进程未能正常终止，将强制终止。")
                flask_process.kill()
                flask_process.join()
        print("服务已关闭.")
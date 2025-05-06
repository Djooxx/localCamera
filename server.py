import asyncio
import websockets # 确保导入
import datetime
import os
from flask import Flask, render_template, send_from_directory
import ssl
from multiprocessing import Process

# --- 配置 ---
HOST = '0.0.0.0'  # 监听所有网络接口
HTTPS_PORT = 5001   # HTTPS端口
WSS_PORT = 8766       # Secure WebSocket端口

RECORDINGS_DIR = "recordings" # 录像保存目录
SEGMENT_DURATION_SECONDS = 60 # 每60秒分段一个文件

# SSL证书文件
CERT_FILE = 'server.crt'
KEY_FILE = 'server.key'

# 服务器在局域网中的IP地址 (必须与SSL证书的CN匹配)
SERVER_LAN_IP = "192.168.1.3"
# --- ---

app = Flask(__name__)

# 确保录像存储目录存在
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# 用于跟踪每个连接的文件和计时器
# {websocket_id: {"file": file_object, "start_time": datetime_object, "path": filepath_to_save}}
active_recordings = {}

@app.route('/')
def index():
    """提供HTML页面"""
    # 客户端JavaScript将连接到WSS (WebSocket Secure)
    wss_address = f"wss://{SERVER_LAN_IP}:{WSS_PORT}"
    return render_template('index.html', ws_address=wss_address)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


# WebSocket连接处理器 (适用于 websockets >= 10.0)
async def video_stream_handler(websocket):
    client_id = id(websocket)
    remote_ip, remote_port = ("unknown", 0)
    if websocket.remote_address:
        remote_ip, remote_port = websocket.remote_address

    # 正确获取客户端请求的路径
    request_path = websocket.request.path

    print(f"客户端 {remote_ip}:{remote_port} (请求路径: '{request_path}') 已通过WSS连接 (ID: {client_id}). 等待视频数据...")

    try:
        async for message in websocket:
            if not isinstance(message, bytes):
                print(f"收到非二进制消息: {message}. 忽略.")
                continue

            now = datetime.datetime.now()

            # 检查是否需要开始新文件或新分段
            if client_id not in active_recordings or \
               (now - active_recordings[client_id]["start_time"]).total_seconds() >= SEGMENT_DURATION_SECONDS:

                # 如果之前有打开的文件，关闭它
                if client_id in active_recordings and active_recordings[client_id]["file"]:
                    active_recordings[client_id]["file"].close()
                    # active_recordings[client_id]['path'] 是文件保存路径
                    print(f"分段文件 {active_recordings[client_id]['path']} 已保存.")

                # 创建新文件
                timestamp = now.strftime("%Y%m%d_%H%M%S")
                # 为每个客户端创建独立的子目录
                client_record_dir = os.path.join(RECORDINGS_DIR, f"client_{str(remote_ip).replace('.', '_')}_{remote_port}")
                os.makedirs(client_record_dir, exist_ok=True)

                file_path_to_save = os.path.join(client_record_dir, f"video_{timestamp}.webm")
                current_file = open(file_path_to_save, "ab") # 追加二进制模式
                active_recordings[client_id] = {
                    "file": current_file,
                    "start_time": now,
                    "path": file_path_to_save # 这是文件保存路径
                }
                print(f"客户端 {client_id}: 开始录制到新文件 {file_path_to_save}")

            # 写入数据
            active_recordings[client_id]["file"].write(message)

    except websockets.exceptions.ConnectionClosedOK:
        print(f"客户端 {remote_ip}:{remote_port} (ID: {client_id}) 正常断开WSS连接.")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"客户端 {remote_ip}:{remote_port} (ID: {client_id}) 异常断开WSS连接: {e}")
    except Exception as e:
        print(f"处理客户端 {client_id} 数据时发生错误: {e}")
        import traceback
        traceback.print_exc() # 打印更详细的错误堆栈
    finally:
        if client_id in active_recordings:
            if active_recordings[client_id]["file"] and not active_recordings[client_id]["file"].closed:
                active_recordings[client_id]["file"].close()
                # active_recordings[client_id]['path'] 是文件保存路径
                if "path" in active_recordings[client_id]:
                     print(f"最终文件 {active_recordings[client_id]['path']} 已保存.")
            del active_recordings[client_id]
        print(f"客户端 {client_id} 处理结束.")


async def start_websocket_server():
    """启动WebSocket Secure (WSS) 服务器"""
    # 在函数内部创建 SSLContext
    ssl_context_ws = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ssl_context_ws.load_cert_chain(CERT_FILE, KEY_FILE)
    except FileNotFoundError:
        print(f"WSS错误: SSL证书 '{CERT_FILE}' 或密钥 '{KEY_FILE}' 未找到。")
        return
    except ssl.SSLError as e:
        print(f"WSS错误: 加载SSL证书/密钥时出错: {e}")
        return

    # 设置一个更大的 max_size，例如 10MB
    # 如果1秒的数据仍然可能超过10MB (例如非常高码率的4K视频)，你可能需要进一步增加它
    # 或者考虑在客户端进一步减小 timeslice
    max_message_size = 10 * 1024 * 1024  # 10 MiB

    async with websockets.serve(
        video_stream_handler,
        HOST,
        WSS_PORT,
        ssl=ssl_context_ws,
        max_size=max_message_size  # <--- 添加或修改此参数
    ):
        print(f"Secure WebSocket (WSS) 服务器正在监听 wss://{SERVER_LAN_IP}:{WSS_PORT} (Max message size: {max_message_size / (1024*1024):.1f} MiB)")
        await asyncio.Future()

def run_flask_app():
    """通过HTTPS运行Flask App"""
    # 在函数内部创建 SSLContext
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
    app.run(host=HOST, port=HTTPS_PORT, ssl_context=ssl_context_flask, debug=False)

if __name__ == "__main__":
    print(f"服务器配置的IP地址: {SERVER_LAN_IP}")
    if SERVER_LAN_IP == "你的服务器局域网IP": # 作为一个额外的检查，虽然我们已经硬编码了
        print("错误: SERVER_LAN_IP 未正确设置为实际IP地址。")
        exit(1)

    if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
        print(f"错误: 找不到SSL证书文件 '{CERT_FILE}' 或密钥文件 '{KEY_FILE}'.")
        print(f"请先使用OpenSSL生成它们，并将CN设置为 {SERVER_LAN_IP}")
        print(f"例如: openssl req -x509 -newkey rsa:2048 -keyout {KEY_FILE} -out {CERT_FILE} -sha256 -days 365 -nodes -subj \"/CN={SERVER_LAN_IP}\"")
        exit(1)
    print("准备启动服务...")

    # Flask进程
    flask_process = Process(target=run_flask_app)

    print("启动HTTPS服务器进程...")
    flask_process.start()

    print("启动Secure WebSocket (WSS) 服务器 (在主进程中)...")
    try:
        asyncio.run(start_websocket_server())
    except KeyboardInterrupt:
        print("服务器正在关闭 (KeyboardInterrupt)...")
    except OSError as e:
        if e.errno == 98 or e.errno == 10048: # Address already in use
             print(f"错误: 端口 {WSS_PORT} (WSS) 或 {HTTPS_PORT} (HTTPS) 已被占用。请检查是否有其他程序在使用这些端口。")
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
import asyncio
import websockets
import datetime
import os
from flask import Flask, render_template, send_from_directory
import ssl
from multiprocessing import Process
import json
import aiofiles

# --- 配置 ---
HOST = '0.0.0.0'
HTTPS_PORT = 5001
WSS_PORT = 8766

RECORDINGS_DIR = "recordings"
MAX_SEGMENT_DURATION_SECONDS = 70

CERT_FILE = 'server.crt'
KEY_FILE = 'server.key'
# 请确保这是你PC服务器的实际局域网IP
SERVER_LAN_IP = "192.168.1.51"
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

async def create_new_segment_file(client_id, remote_ip, remote_port, extension=".mp4"):
    """辅助函数：异步关闭旧文件并创建新分段文件"""
    global active_recordings

    if client_id in active_recordings and active_recordings[client_id].get("file"):
        await active_recordings[client_id]["file"].close()
        print(f"客户端 {client_id}: 分段文件 {active_recordings[client_id]['path']} 已保存.")

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    client_record_dir = os.path.join(RECORDINGS_DIR, f"client_{str(remote_ip).replace('.', '_')}_{remote_port}")
    os.makedirs(client_record_dir, exist_ok=True)

    file_path_to_save = os.path.join(client_record_dir, f"video_{timestamp}{extension}")

    # 使用 aiofiles 异步打开文件，防止阻塞事件循环
    current_file = await aiofiles.open(file_path_to_save, "ab")

    active_recordings[client_id] = {
        "file": current_file,
        "start_time": now,
        "path": file_path_to_save,
        "extension": extension
    }
    print(f"客户端 {client_id}: 开始录制到新文件 {file_path_to_save}")

async def video_stream_handler(websocket):
    client_id = id(websocket)
    remote_ip, remote_port = ("unknown", 0)
    if websocket.remote_address:
        remote_ip, remote_port = websocket.remote_address

    print(f"客户端 {remote_ip}:{remote_port} 已通过WSS连接 (ID: {client_id}). 等待初始化信号...")

    try:
        async for message in websocket:
            now = datetime.datetime.now()

            # 处理 JSON 文本控制信号
            if isinstance(message, str):
                try:
                    control_data = json.loads(message)
                    msg_type = control_data.get("type")

                    if msg_type == "init":
                        ext = control_data.get("extension", ".mp4")
                        print(f"客户端 {client_id}: 收到初始化信号，采用格式 {ext}")
                        await create_new_segment_file(client_id, remote_ip, remote_port, ext)

                    elif msg_type == "new_segment_signal":
                        print(f"客户端 {client_id}: 收到分段信号，准备切换文件。")
                        ext = active_recordings.get(client_id, {}).get("extension", ".mp4")
                        await create_new_segment_file(client_id, remote_ip, remote_port, ext)

                except json.JSONDecodeError:
                    print(f"客户端 {client_id}: 收到无法解析的JSON: {message}")
                continue

            # 处理二进制视频流
            if not isinstance(message, bytes):
                continue

            # 服务器端最大分段时长兜底检查
            if client_id in active_recordings and \
               (now - active_recordings[client_id]["start_time"]).total_seconds() >= MAX_SEGMENT_DURATION_SECONDS:
                print(f"客户端 {client_id}: 达到服务器最大时长，强制分段。")
                ext = active_recordings[client_id].get("extension", ".mp4")
                await create_new_segment_file(client_id, remote_ip, remote_port, ext)

            # 确保文件已打开
            if client_id not in active_recordings or not active_recordings[client_id].get("file"):
                print(f"客户端 {client_id}: 警告 - 数据先于init到达，默认按mp4存储。")
                await create_new_segment_file(client_id, remote_ip, remote_port, ".mp4")

            # 异步写入视频块数据
            await active_recordings[client_id]["file"].write(message)

    except websockets.exceptions.ConnectionClosedOK:
        print(f"客户端 (ID: {client_id}) 正常断开连接.")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"客户端 (ID: {client_id}) 异常断开: {e}")
    except Exception as e:
        print(f"处理客户端 {client_id} 时发生错误: {e}")
    finally:
        # 清理资源
        if client_id in active_recordings:
            f = active_recordings[client_id].get("file")
            if f and not f.closed:
                await f.close()
                print(f"最终文件 {active_recordings[client_id]['path']} 已保存.")
            del active_recordings[client_id]

async def start_websocket_server():
    ssl_context_ws = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ssl_context_ws.load_cert_chain(CERT_FILE, KEY_FILE)
    except FileNotFoundError:
        print(f"WSS错误: SSL证书 '{CERT_FILE}' 或密钥 '{KEY_FILE}' 未找到。")
        return

    max_message_size = 10 * 1024 * 1024
    async with websockets.serve(
        video_stream_handler, HOST, WSS_PORT, ssl=ssl_context_ws, max_size=max_message_size
    ):
        print(f"WSS 服务器正在监听 wss://{SERVER_LAN_IP}:{WSS_PORT}")
        await asyncio.Future()

def run_flask_app():
    ssl_context_flask = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ssl_context_flask.load_cert_chain(CERT_FILE, KEY_FILE)
    except FileNotFoundError:
        print("Flask HTTPS错误: SSL证书未找到。")
        return

    print(f"HTTPS 访问入口: https://{SERVER_LAN_IP}:{HTTPS_PORT}")
    app.run(host=HOST, port=HTTPS_PORT, ssl_context=ssl_context_flask, debug=False)

if __name__ == "__main__":
    if SERVER_LAN_IP == "你的服务器局域网IP" or not SERVER_LAN_IP:
        print("错误: 请先配置 SERVER_LAN_IP")
        exit(1)

    if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
        print(f"错误: 找不到SSL证书。生成命令: openssl req -x509 -newkey rsa:2048 -keyout {KEY_FILE} -out {CERT_FILE} -sha256 -days 365 -nodes -subj \"/CN={SERVER_LAN_IP}\"")
        exit(1)

    flask_process = Process(target=run_flask_app)
    flask_process.start()

    try:
        asyncio.run(start_websocket_server())
    except KeyboardInterrupt:
        print("服务器正在关闭...")
    finally:
        if flask_process.is_alive():
            flask_process.terminate()
            flask_process.join(timeout=5)
        print("服务已关闭.")

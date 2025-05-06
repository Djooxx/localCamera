# Local Camera Streaming and Recording

这是一个通过网页浏览器（特别是针对移动设备如iPad优化）捕获摄像头视频流，并将其安全地传输到本地服务器进行分段录制和保存的项目。

## 主要功能

*   **实时视频流**: 通过浏览器使用 `getUserMedia` API 捕获摄像头画面。
*   **安全传输**: 使用 HTTPS 协议提供网页服务，使用 WSS (Secure WebSockets) 协议传输视频数据。
*   **分段录制**: 视频流在服务器端被接收并按固定时长（默认为60秒）分段保存为 `.webm` 文件。
*   **客户端特定存储**: 每个连接的客户端的录像会保存在以其 IP 地址和端口命名的独立子目录中，位于 `recordings` 文件夹下。
*   **跨平台**: 客户端部分是 HTML 和 JavaScript，可在支持相关 Web API 的现代浏览器上运行。
*   **Python 后端**: 服务器端使用 Flask 处理 HTTP 请求，使用 `websockets` 库处理 WebSocket 连接。

## 项目结构

```
localCamera/
├── recordings/             # 录制的视频文件存放目录 (自动创建)
│   └── client_<ip>_<port>/ # 每个客户端的录像子目录
│       └── video_<timestamp>.webm
├── templates/
│   └── index.html          # 前端页面，用于捕获和发送视频流
├── venv/                   # Python 虚拟环境 (建议)
├── server.crt              # SSL 证书文件
├── server.key              # SSL 私钥文件
├── server.py               # 后端服务器逻辑 (Flask + WebSocket)
└── README.md               # 本文件
```

## 安装与配置

1.  **环境准备**:
    *   确保已安装 Python 3.x。
    *   建议创建并激活一个 Python 虚拟环境：
        ```bash
        python -m venv venv
        # Windows
        .\venv\Scripts\activate
        # macOS/Linux
        # source venv/bin/activate
        ```

2.  **安装依赖**: 
    项目主要依赖 `Flask` 和 `websockets`。可以通过 pip 安装：
    ```bash
    pip install Flask websockets
    ```

3.  **生成 SSL 证书**:
    项目需要 `server.crt` 和 `server.key` 文件用于 HTTPS 和 WSS。如果文件不存在，`server.py` 启动时会提示如何生成。你需要将 `server.py` 中 `SERVER_LAN_IP` 变量的值（默认为 `192.168.1.3`）替换为你服务器在局域网中的实际 IP 地址，并在生成证书时使用此 IP 作为通用名称 (CN)。
    例如，如果你的服务器IP是 `192.168.1.100`，则生成命令如下：
    ```bash
    openssl req -x509 -newkey rsa:2048 -keyout server.key -out server.crt -sha256 -days 365 -nodes -subj "/CN=192.168.1.100"
    ```
    将生成的 `server.crt` 和 `server.key` 文件放置在项目根目录。

4.  **配置服务器IP**: 
    打开 `server.py` 文件，修改以下配置项：
    ```python
    # ...
    # SSL证书文件
    CERT_FILE = 'server.crt'
    KEY_FILE = 'server.key'

    # 服务器在局域网中的IP地址 (必须与SSL证书的CN匹配)
    SERVER_LAN_IP = "你的服务器实际局域网IP地址" # 例如 "192.168.1.100"
    # ...
    ```
    确保 `SERVER_LAN_IP` 的值与你生成 SSL 证书时使用的 CN (Common Name) 一致。

## 如何运行

1.  确保已完成上述安装与配置步骤。
2.  激活虚拟环境（如果使用了）。
3.  在项目根目录下运行服务器脚本：
    ```bash
    python server.py
    ```
4.  服务器启动后，会显示监听的 HTTPS 和 WSS 地址。例如：
    ```
    HTTPS 服务器正在监听 https://192.168.1.100:5001
    请在移动设备或PC浏览器中打开 https://192.168.1.100:5001
    Secure WebSocket (WSS) 服务器正在监听 wss://192.168.1.100:8766 ...
    ```
5.  在客户端设备（如 移动设备 或 PC）的浏览器中打开 `https://<SERVER_LAN_IP>:<HTTPS_PORT>` (例如 `https://192.168.1.100:5001`)。
    *   由于使用的是自签名证书，浏览器可能会提示安全警告，你需要接受风险并继续访问。
    *   如ios的WebSocket仍不能正常访问,将crt文件导入到手机的设置中,并信任证书
6.  点击页面上的 “开始录制” 按钮。

## 注意事项

*   **防火墙**: 确保服务器的防火墙允许设定的 HTTPS 端口 (默认为 `5001`) 和 WSS 端口 (默认为 `8766`) 的入站连接。
*   **浏览器兼容性**: `getUserMedia` 和 `MediaRecorder` API 的支持情况因浏览器和操作系统而异。项目中的 `index.html` 包含对这些 API 的检查。iOS Safari 对 MediaRecorder 的支持相对有限，WebM (VP8/VP9) 是推荐的格式。
*   **网络环境**: 客户端和服务器需要在同一局域网内，或者服务器具有公网可访问的配置（需要更复杂的网络设置和安全考虑）。
*   **录像文件**: 录制的视频文件会保存在项目根目录下的 `recordings` 文件夹内，并根据客户端 IP 和端口分目录存放。

## 常见问题 (Troubleshooting)

*   **浏览器无法访问摄像头**:
    *   确保您已在浏览器提示时授权网页访问摄像头和麦克风。
    *   检查浏览器设置，确保没有全局禁止摄像头访问。
    *   尝试在不同的浏览器中打开页面，以排除特定浏览器兼容性问题。

*   **无法连接到服务器 (HTTPS 或 WSS)**:
    *   确认服务器已正确运行，并且 `server.py` 脚本没有报错。
    *   检查 `server.py` 中的 `SERVER_LAN_IP` 配置是否为服务器在局域网中的实际 IP 地址。
    *   确保客户端设备与服务器在同一局域网内。
    *   检查服务器防火墙设置，确保 HTTPS 端口 (默认为 `5001`) 和 WSS 端口 (默认为 `8766`) 已开放。
    *   对于 HTTPS 连接，由于使用的是自签名证书，您需要在浏览器中接受安全风险。

*   **视频无法录制或保存**:
    *   查看服务器端 `server.py` 的控制台输出，检查是否有错误信息。
    *   确保 `recordings` 目录有写入权限。
    *   检查浏览器控制台是否有 `MediaRecorder` 相关的错误。

## 客户端 (templates/index.html)

客户端页面 (`index.html`) 包含以下主要逻辑：

*   请求用户授权访问摄像头和麦克风。
*   获取媒体流并在 `<video>` 元素中预览。
*   建立到服务器的 Secure WebSocket (WSS) 连接。
*   初始化 `MediaRecorder`，将媒体流编码为指定的 `MimeType` (默认为 `video/webm; codecs="vp8, opus"`)。
*   以固定的时间间隔 (timeslice，默认为1秒) 将编码后的数据块通过 WebSocket 发送到服务器。
*   提供开始/停止录制的按钮和状态显示。
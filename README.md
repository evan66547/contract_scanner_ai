# 🎯 Contract Scanner AI

[![license](https://img.shields.io/badge/license-Personal_Use-important.svg)](https://github.com/evan66547/contract_scanner_ai/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.10~3.12-yellow.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-black.svg)](https://ollama.com/)

[English](#english) | [中文](#chinese)

---

<span id="english"></span>
## 🇬🇧 English

**Contract Scanner AI** is an OCR-based text scanning and matching application. It uses a mobile device's web browser as the camera input, sending video frames over WebSockets to a local PC or Mac server. The server processes these frames using OCR (via local Ollama models or cloud APIs) to extract text. The extracted text is then compared against a predefined list of target strings (such as company names or contract numbers) using fuzzy matching on the client side, providing real-time feedback when a match is found.

> **Origin Story**: As a legal professional handling debt recovery work, I often faced the daunting task of searching for original evidence documents among mountains of paperwork. This tool was born out of that frustration — to turn hours of manual searching into seconds of automated scanning.

### ✨ Key Technical Features

- **🧠 Multi-Engine OCR Backend (FastAPI)**
  - Seamlessly switch between **Ollama (Local GLM-OCR)**, **Baidu Cloud OCR**, **PaddleOCR (Offline)**, and **OCR.Space**.
  - Baidu OCR: 6-API automatic fallback chain — when one API's free quota is exhausted, it automatically switches to the next available endpoint.
  - Built-in VRAM protection: Auto-warms up local models, strictly limits concurrent Ollama inferences to prevent Out-Of-Memory crashes, and multiplexes WebSockets.
- **⚡ Real-Time WebSocket Streaming**
  - Mobile client (`app.js`) extracts camera frames via HTML5 Canvas and streams them to the server continuously without REST overhead.
- **🎯 Client-Side Fuzzy Matching**
  - Matches OCR results against `targets.json` entirely in the browser using tunable **Levenshtein distance**, prefix verification, and dynamic Region of Interest (ROI) cropping.
  - Triggers native **Haptic Feedback (Vibration)** upon successful hits.
- **📊 Smart Admin Dashboard**
  - Modern `admin.html` control panel. Drag-and-drop Excel/CSV files for auto-mapping target columns.
  - Live configuration editor (adjust scan intervals, matching confidence, OCR engine, and model selection) without restarting the server.
- **📱 Automated ADB Integration**
  - "Open on Phone" button triggers `adb reverse tcp:8080 tcp:8080` and automatically launches the intent on connected Android devices for true offline usability.

### 🚀 Quick Start

**1. Prerequisites**
- [Python 3.10-3.12](https://www.python.org/downloads/) installed. (PaddleOCR requires Python <=3.12)
- (Optional) [Ollama](https://ollama.com/) for local AI OCR: `ollama run glm-ocr`

**2. Run the Server**
```bash
git clone https://github.com/evan66547/contract_scanner_ai.git
cd contract_scanner_ai
```
- **Mac / Linux**: `bash run.sh`
- **Windows**: Double-click `deploy.bat` (recommended, auto-downloads ADB if missing) or `run.bat` (lightweight)
*(The script automatically configures the venv, installs dependencies, and launches the FastAPI server).*

**3. Usage**
- Open **Admin Panel** on PC: `http://localhost:8080/admin.html`
- **Open Scanner on Mobile (Two Ways):**
  - **Wireless Connection:** Connect your phone to the same Wi-Fi network as your PC and access the server's local IP (e.g., `http://192.168.1.x:8080`).
  - **Wired (USB) Connection:** Connect via USB and click "Open on Phone" in the admin panel to auto-launch via ADB.
  - **iOS (iPhone/iPad) via Tailscale:**
    1. Install [Tailscale](https://tailscale.com/download) on both Mac and iPhone, log in with the same account
    2. Enable **HTTPS Certificates** and **MagicDNS** in [Tailscale admin console](https://login.tailscale.com/admin/dns)
    3. Run on Mac: `tailscale serve --bg http://localhost:8080`
    4. Open Safari on iPhone and visit `https://<machine>.<tailnet>.ts.net`
    5. Allow camera permission when prompted

---

<span id="chinese"></span>
## 🇨🇳 中文

**Contract Scanner AI** 是一个基于 OCR 的文本扫描与匹配工具。系统利用移动端网页浏览器采集摄像头画面，通过 WebSocket 将视频帧实时传输至运行在 PC/Mac 的本地服务端。服务端调用 OCR 引擎（本地 Ollama 模型或云端 API）提取画面文本，前端随后将提取到的文本与预设的目标清单（如企业名称、合同编号）进行模糊匹配，并在匹配成功时提供实时反馈。

> **开发背景**：作为一个法务，在做清欠工作寻找证据原件的时候，常常面对成堆的文件，一份一份翻找既耗时又容易遗漏。这个工具就是为了解决这个痛点而开发的——用手机摄像头扫一扫，秒级定位目标文件。

### ✨ 核心技术架构

- **🧠 多引擎 OCR 后端 (基于 FastAPI)**
  - 支持热切换 4 种底层引擎：**Ollama (本地 GLM-OCR 等)**、**百度智能云 OCR**、**PaddleOCR (纯离线)**、以及 **OCR.Space**。
  - 百度 OCR 内置 6 个 API 自动降级链：单个接口免费额度用尽时，自动切换到下一个可用接口，最大化利用免费资源。
  - **显存保护机制**：服务器启动时自动侦测并预热本地模型；针对 Ollama 引擎严格实施 `Semaphore(1)` 并发控制，完美杜绝 VRAM 溢出导致的进程崩溃。
- **⚡ WebSocket 实时推流识别**
  - 手机端 (`app.js`) 灵活调用 HTML5 `mediaDevices` 抓取定制化感兴趣区域 (ROI) 的视频帧，借助 WebSocket 双向通道达成极低延迟的数据交换。
- **🎯 纯前端高并发模糊匹配**
  - 收到 OCR 识别结果后，在浏览器端利用 **Levenshtein 编辑距离算法** 与缓存的 `targets.json` 进行高效碰撞比对。
  - 支持高度自定义的容错率、匹配长度阈值，并在匹配成功时自动调用 HTML5 Vibration API 触发物理震动反馈。
- **📊 动态配置管理驾驶舱**
  - 极致优雅的 `admin.html` 控制台。支持直接拖拽 Excel/CSV 表格自动映射所需的数据列，直接解析。
  - 所有核心参数（轮询间隔、容错率、引擎切换）均可在此面板实时调优并持久化到配置，无需重启服务端。
- **📱 ADB 深度自动化整合**
  - 后端集成了 ADB 命令执行环境，点击面板的“在手机上打开”即可全自动执行端口反向映射 (`adb reverse`) 并唤起安卓设备默认浏览器，完美适应“无局域网”、“纯内网”等严苛作业环境。

### 🚀 极速起步

**1. 前置环境**
- 安装 [Python 3.10-3.12](https://www.python.org/downloads/)（PaddleOCR 不兼容 3.13+）
- (可选) 安装 [Ollama](https://ollama.com/) 用于本地 AI OCR：`ollama run glm-ocr`

**2. 启动服务**
```bash
git clone https://github.com/evan66547/contract_scanner_ai.git
cd contract_scanner_ai
```
- **Mac / Linux 用户**: 直接执行 `bash run.sh`
- **Windows 用户**: 直接双击 `deploy.bat`（推荐，自动检测并下载 ADB）或 `run.bat`（轻量版）
*(启动脚本会自动创建 `.venv` 虚拟环境、拉取包依赖并挂起 FastAPI 守护进程)*

**3. 如何使用**
- 在电脑端打开**管理台**: `http://localhost:8080/admin.html`，可拖入 Excel 导入你的目标名单。
- **在手机端打开扫描器 (两种方式)**: 
  - **无线连接 (推荐)**: 确保手机和电脑连接在同一局域网 (Wi-Fi)，使用手机浏览器直接访问电脑的局域网 IP (例如 `http://192.168.1.x:8080`) 即可随时随地无线扫描。
  - **有线连接 (ADB)**: 在安卓手机插线后，直接点击管理台中右上角的“在手机上打开”按钮。
  - **iOS (iPhone/iPad) 通过 Tailscale**: 
    1. Mac 与 iPhone 安装 [Tailscale](https://tailscale.com/download) 并登录**同一账号**
    2. Tailscale [管理后台](https://login.tailscale.com/admin/dns) 启用 **HTTPS Certificates** 与 **MagicDNS**
    3. Mac 终端运行：`tailscale serve --bg http://localhost:8080`
    4. iPhone Safari 访问 `https://<设备名>.<tailnet>.ts.net`
    5. 允许摄像头权限后即可扫描

> 🔐 **隐私及安全提示**: 为了开源安全，本仓库中的代码已剥离硬编码的 API 密钥及隐私名单数据。如需使用百度 OCR 等云端服务，请在启动服务后前往管理面板的“设置”项中自行安全配置。

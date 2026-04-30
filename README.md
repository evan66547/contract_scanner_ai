# 🎯 Contract Scanner AI

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/evan66547/contract_scanner_ai/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.9+-yellow.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-black.svg)](https://ollama.com/)

[English](#english) | [中文](#chinese)

---

<span id="english"></span>
## 🇬🇧 English

**Contract Scanner AI** is a real-time, hardware-independent intelligent scanning system. It turns any mobile browser into a wireless scanner, streaming camera frames via WebSockets to a PC/Mac backend. The backend runs OCR inferences (via local Ollama or cloud APIs), and the frontend performs dynamic fuzzy matching against a loaded target list (e.g., enterprise contracts, logistics entities).

### ✨ Key Technical Features

- **🧠 Multi-Engine OCR Backend (FastAPI)**
  - Seamlessly switch between **Ollama (Local GLM-OCR)**, **Baidu Cloud OCR**, and **OCR.Space**.
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
- [Python 3.9+](https://www.python.org/downloads/) & [Ollama](https://ollama.com/) installed.
- (Optional) Pull the vision model: `ollama run glm-ocr`

**2. Run the Server**
```bash
git clone https://github.com/evan66547/contract_scanner_ai.git
cd contract_scanner_ai
```
- **Mac / Linux**: `bash run.sh`
- **Windows**: Double-click `start.bat`
*(The script automatically configures the venv, installs dependencies, and launches the FastAPI server).*

**3. Usage**
- Open **Admin Panel** on PC: `http://localhost:8080/admin.html`
- **Open Scanner on Mobile (Two Ways):**
  - **Wireless Connection:** Connect your phone to the same Wi-Fi network as your PC and access the server's local IP (e.g., `http://192.168.1.x:8080`).
  - **Wired (USB) Connection:** Connect via USB and click "Open on Phone" in the admin panel to auto-launch via ADB.

---

<span id="chinese"></span>
## 🇨🇳 中文

**Contract Scanner AI** 是一套支持硬件解耦、支持实时视频流处理的智能目标实体追猎系统。它通过 WebSocket 将手机浏览器的相机帧实时串流至 PC/Mac 后端。后端利用本地大模型或云端 OCR 提取文本后，前端即时执行模糊匹配，实现“点石成金”的智能扫码体验。

### ✨ 核心技术架构

- **🧠 多引擎 OCR 后端 (基于 FastAPI)**
  - 支持热切换 3 种底层引擎：**Ollama (本地 GLM-OCR 等)**、**百度智能云 OCR**、以及 **OCR.Space**。
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
- 安装 [Python 3.9+](https://www.python.org/downloads/) 与 [Ollama](https://ollama.com/)
- (可选) 下载默认的本地视觉模型：`ollama run glm-ocr`

**2. 启动服务**
```bash
git clone https://github.com/evan66547/contract_scanner_ai.git
cd contract_scanner_ai
```
- **Mac / Linux 用户**: 直接执行 `bash run.sh`
- **Windows 用户**: 直接双击 `start.bat`
*(启动脚本会自动创建 `.venv` 虚拟环境、拉取包依赖并挂起 FastAPI 守护进程)*

**3. 如何使用**
- 在电脑端打开**管理台**: `http://localhost:8080/admin.html`，可拖入 Excel 导入你的目标名单。
- **在手机端打开扫描器 (两种方式)**: 
  - **无线连接 (推荐)**: 确保手机和电脑连接在同一局域网 (Wi-Fi)，使用手机浏览器直接访问电脑的局域网 IP (例如 `http://192.168.1.x:8080`) 即可随时随地无线扫描。
  - **有线连接 (ADB)**: 在安卓手机插线后，直接点击管理台中右上角的“在手机上打开”按钮。

> 🔐 **隐私及安全提示**: 为了开源安全，本仓库中的代码已剥离硬编码的 API 密钥及隐私名单数据。如需使用百度 OCR 等云端服务，请在启动服务后前往管理面板的“设置”项中自行安全配置。

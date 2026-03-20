# 🎯 Contract Scanner AI

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/evan66547/contract_scanner_ai/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.9+-yellow.svg)](https://www.python.org/downloads/)
[![AI Engine](https://img.shields.io/badge/AI%20Engine-GLM--OCR-0071e3.svg)](https://huggingface.co/THUDM/glm-4v-9b)
[![Status](https://img.shields.io/badge/Status-Stable-success.svg)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)]()

[English](#english) | [中文](#chinese)

---

<span id="english"></span>
## 🇬🇧 English

A smart, **100% local, privacy-focused** AI scanner system powered by edge-computing and the GLM-OCR vision model. It turns your mobile device into a powerful wireless scanner while processing all neural network inferences entirely offline on your Mac/PC to ensure absolute data privacy. Designed for enterprise contract tracking, event sign-ins, and generic logistics matching.

### ✨ Highlights

*   🔒 **Absolute Privacy (Local-First)**: OCR inferences run directly on your host machine via Ollama. Zero data leaves your network.
*   ⚡ **Edge-AI Performance**: Built on Zhipu's **GLM-OCR** to solve complex lighting, angles, and shadows that break traditional deterministic algorithms.
*   🎯 **Fuzzy Matching & ROI Cropping**: Features Levenshtein distance tolerance, keyword triggering, and customizable Region of Interest (ROI) scanning.
*   📊 **Dynamic Data Loading**: Built-in modern web dashboard to drag-and-drop Excel/CSV files and seamlessly map target names.
*   📱 **Zero-Install Mobile Client**: Access the scanner purely via your phone's browser through ADB port forwarding. Supports haptic vibration feedback upon successful hits.

### 🚀 Quick Start (1-Click Run)

**1. Prerequisites**
*   Install [Python 3.9+](https://www.python.org/downloads/) and [Ollama](https://ollama.com/)
*   Pull the vision model: `ollama run glm-ocr`

**2. Clone & Run**
```bash
git clone https://github.com/evan66547/contract_scanner_ai.git
cd contract_scanner_ai
```

*   **Mac / Linux**: Run `bash run.sh` in the terminal.
*   **Windows**: Simply double-click `start.bat`.

The scripts will automatically inject virtual environments, install dependencies, and launch the server! Follow the terminal output to open your Desktop Dashboard and Mobile Scanner.

<details>
<summary><b>🛠️ Manual Developer Setup</b></summary>
<br>

If you prefer to manually configure your environments without using the automated scripts:
```bash
pip install -r requirements.txt
python3 server.py
```
*Phone connect via USB*: `adb reverse tcp:8080 tcp:8080`
</details>

---

<span id="chinese"></span>
## 🇨🇳 中文

**Contract Scanner AI** 是一套具有高度商业落地潜力的通用目标实体追猎与核验系统。它利用手机浏览器作为“无线扫码枪”，在本地（PC/Mac）运行底层的 **GLM-OCR** 视觉大模型引擎完成解析。支持容错匹配、编辑距离纠错，适用于各类企业的档案盘点、会场签到及物流单号对齐。

### ✨ 核心特性

*   🔒 **完全纯血本地化 (Privacy-Focused)**：OCR 及匹配链路彻底脱机运行，没有无端的外部网络请求，保障极密商业数据绝不出域。
*   ⚡ **边缘 AI (Edge-Computing)**：原生适配 Apple Metal 硬件加速（基于 Ollama），告别传统 OpenCV 二值化的繁琐参数调优，对复杂光照、阴影和模糊具备极高鲁棒性。
*   🎯 **智能模糊搜索**：内置 Levenshtein（编辑距离）算法、缩写匹配与词缀匹配，极大程度抹平日产错别字或光学识别导致的误差。
*   📊 **动态数据驾驶舱**：配备具备极致 UI/UX 的管理面板，支持拖拽批量导入 Excel / CSV，智能映射匹配主键。
*   📱 **极简跨端协同**：手机端免安装 App，基于 HTML5 和 ADB 反向映射搭建，扫中目标后自动触发手机震动物理反馈。

*注：开源仓库的代码已经过 100% 商业隐私脱敏，去除了所有硬编码定名，转化为泛用的识别系统架构。*

### 🚀 极速起步 (一键双击包)

**1. 前置准备**
*   安装 [Python 3.9+](https://www.python.org/downloads/) 与 [Ollama](https://ollama.com/)
*   下载大模型（只需执行一次）：`ollama run glm-ocr`

**2. 获取代码与运行**
```bash
git clone https://github.com/evan66547/contract_scanner_ai.git
cd contract_scanner_ai
```

*   **Mac / Linux 极简启动**: 在终端执行 `bash run.sh`
*   **Windows 懒人包**: 直接双击文件夹中的 `start.bat`

全自动脚本将**智能建立虚拟环境、下载必需库并秒切启动**，全程无需人工干预！请直接参考终端输出的提示去访问电脑控制台面板，或通过安卓连线模式连接你的手机。

<details>
<summary><b>🛠️ 极客纯手工启动方式</b></summary>
<br>

如果你更喜欢全局裸装依赖并用命令行掌控一切：
```bash
pip install -r requirements.txt
python3 server.py
```
*通过数据线映射手机端口以便断网使用*：`adb reverse tcp:8080 tcp:8080`
</details>

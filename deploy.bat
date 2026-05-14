@echo off
chcp 65001 >nul 2>&1
title Contract Scanner AI - Windows 一键部署
echo ==========================================
echo  Contract Scanner AI - Windows 一键部署
echo ==========================================

:: 1. 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] 未检测到 Python
    echo.
    echo 请按以下步骤安装：
    echo 1. 访问 https://www.python.org/downloads/
    echo 2. 下载 Python 3.12（Windows installer 64-bit）
    echo 3. 安装时勾选 "Add python.exe to PATH"
    echo 4. 重新打开此窗口，再次运行 deploy.bat
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%a in ('python --version') do set PYVER=%%a
echo [OK] Python %PYVER%

:: 2. 检查/自动下载 ADB
echo.
echo [~] 检查 ADB (Android Debug Bridge)...
where adb >nul 2>&1
if errorlevel 1 (
    echo [~] 未检测到 ADB，正在自动下载...
    if not exist tools\platform-tools\adb.exe (
        if not exist tools mkdir tools
        echo 正在下载 Android SDK Platform Tools (~10MB)...
        powershell -Command "Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile 'tools\platform-tools.zip'" >nul 2>&1
        if errorlevel 1 (
            echo [X] 下载失败，请检查网络连接
            echo 手动下载地址: https://developer.android.com/tools/releases/platform-tools
            pause
            exit /b 1
        )
        echo 正在解压...
        powershell -Command "Expand-Archive -Path 'tools\platform-tools.zip' -DestinationPath 'tools' -Force" >nul 2>&1
        del tools\platform-tools.zip >nul 2>&1
    )
    set "PATH=%CD%\tools\platform-tools;%PATH%"
    echo [OK] ADB 已自动配置 (tools\platform-tools)
) else (
    echo [OK] ADB 已安装
)

:: 3. 虚拟环境
if not exist .venv (
    echo.
    echo [~] 创建 Python 虚拟环境...
    python -m venv .venv
)
call .venv\Scripts\activate.bat >nul 2>&1
echo [OK] 虚拟环境已激活

:: 4. 安装依赖
echo.
echo [~] 安装 Python 依赖...
pip install -r requirements.txt --quiet >nul 2>&1
if errorlevel 1 (
    echo [X] 依赖安装失败，尝试完整输出...
    pip install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] 依赖安装完成

:: 5. 检查 Ollama
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [!] Ollama 未运行（如需本地 OCR 引擎，请访问 https://ollama.com 安装）
) else (
    echo [OK] Ollama 运行中
)

:: 6. 启动
echo.
echo ==========================================
echo  部署完成！正在启动服务...
echo ==========================================
echo PC 管理面板:  http://localhost:8080/admin.html
echo 手机扫描端:   http://localhost:8080
echo ------------------------------------------
echo 按 Ctrl+C 停止服务
echo.
python server.py

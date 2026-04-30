@echo off
setlocal

set VENV_DIR=.venv

echo ==========================================
echo 🚀 Starting Contract Scanner AI (Windows)
echo ==========================================

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Error: Python 3 is not installed or not added to PATH.
    echo ⚠️ Please install Python 3.9+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 2. Create Virtual Environment
if not exist "%VENV_DIR%" (
    echo 👉 Creating virtual environment (%VENV_DIR%)...
    python -m venv %VENV_DIR%
)

:: 3. Activate Virtual Environment
call %VENV_DIR%\Scripts\activate.bat
echo ✅ Virtual environment activated.

:: 4. Install Dependencies
echo 📦 Installing/verifying dependencies...
pip install -r requirements.txt --quiet
echo ✅ Dependencies installed.

:: 5. Start Server
echo ------------------------------------------
echo 🌐 PC Dashboard: http://localhost:8080/admin.html
echo 📱 Mobile Scanner: http://localhost:8080
echo    (Use ADB reverse to access offline via USB: adb reverse tcp:8080 tcp:8080)
echo ------------------------------------------
echo 🚀 Server is running. Close this window or press Ctrl+C to stop.
python server.py

pause

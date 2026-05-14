@echo off
chcp 65001 >nul 2>&1
echo ==========================================
echo  Starting Contract Scanner AI (Windows)
echo ==========================================

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python 3.10-3.12 first.
    exit /b 1
)

set VENV_DIR=.venv

REM Create venv if not exists
if not exist %VENV_DIR% (
    echo Creating virtual environment (%VENV_DIR%)...
    python -m venv %VENV_DIR%
)

REM Activate
 call %VENV_DIR%\Scripts\activate.bat
echo Virtual environment activated.

REM Install deps
echo Installing dependencies...
pip install -r requirements.txt --quiet >nul 2>&1
echo Dependencies installed.

REM Check Ollama
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo Warning: Ollama service not running on port 11434.
    echo Please start Ollama and pull the 'glm-ocr' model.
)

echo ------------------------------------------
echo PC Dashboard:    http://localhost:8080/admin.html
echo Mobile Scanner:  http://localhost:8080
echo ------------------------------------------
echo Server running. Press Ctrl+C to stop.
python server.py

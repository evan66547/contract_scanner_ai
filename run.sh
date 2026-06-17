#!/bin/bash

echo "=========================================="
echo " 🚀 Starting Contract Scanner AI (Mac/Linux)"
echo "=========================================="

# 1. Check Python 3.12 (PaddleOCR requires <=3.12)
PYTHON_CMD=""
for p in python3.12 python3.11 python3.10; do
    if command -v $p &> /dev/null; then
        PYTHON_CMD=$p
        break
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    echo "❌ Error: Python 3.10-3.12 required (PaddleOCR incompatible with 3.13+)."
    exit 1
fi

VENV_DIR=".venv"

# 2. Check and Create Virtual Environment
if [ ! -d "$VENV_DIR" ]; then
    echo "👉 Creating virtual environment ($VENV_DIR) with $PYTHON_CMD..."
    $PYTHON_CMD -m venv $VENV_DIR
fi

# 3. Activate Virtual Environment
source $VENV_DIR/bin/activate
echo "✅ Virtual environment activated."

# 4. Install Dependencies
echo "📦 Installing/verifying dependencies..."
pip install -r requirements.txt --quiet
echo "✅ Dependencies installed."

# 5. Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags >/dev/null; then
    echo "⚠️ Warning: Ollama service does not seem to be running on port 11434."
    echo "⚠️ Please ensure you have started Ollama and pulled the 'glm-ocr' model."
fi

# 6. Start the Server
echo "------------------------------------------"
PORT=${PORT:-8093}
LAN_IP=""
if command -v ipconfig >/dev/null 2>&1; then
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || true)
fi
if [ -z "$LAN_IP" ] && [ -x /usr/sbin/ipconfig ]; then
    LAN_IP=$(/usr/sbin/ipconfig getifaddr en0 2>/dev/null || true)
fi
if [ -z "$LAN_IP" ] && command -v hostname >/dev/null 2>&1; then
    LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
fi
if [ -z "$LAN_IP" ] && command -v ifconfig >/dev/null 2>&1; then
    LAN_IP=$(ifconfig 2>/dev/null | awk '/inet / && $2 !~ /^127\\./ && $2 ~ /^(192\\.168\\.|10\\.|172\\.(1[6-9]|2[0-9]|3[0-1])\\.)/ {print $2; exit}')
fi
echo "🌐 PC Dashboard: http://localhost:${PORT}/admin.html"
if [ -n "$LAN_IP" ]; then
    echo "📱 Same Wi-Fi Scanner: http://${LAN_IP}:${PORT}"
else
    echo "📱 Same Wi-Fi Scanner: open Admin Panel to view LAN address"
fi
echo "📱 USB/ADB Scanner: http://localhost:${PORT}"
echo "   (Use ADB reverse to access via USB: adb reverse tcp:${PORT} tcp:${PORT})"
# iOS scanning requires Tailscale HTTPS tunnel (see admin panel for setup)
echo "------------------------------------------"
echo "🚀 Server is running. Press Ctrl+C to stop."
"$VENV_DIR/bin/python" server.py

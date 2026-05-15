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
PORT=${PORT:-8080}
echo "🌐 PC Dashboard: http://localhost:${PORT}/admin.html"
echo "📱 Mobile Scanner: http://localhost:${PORT}"
echo "   (Use ADB reverse to access via USB: adb reverse tcp:${PORT} tcp:${PORT})"
echo "------------------------------------------"
echo "🚀 Server is running. Press Ctrl+C to stop."
python3 server.py

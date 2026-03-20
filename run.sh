#!/bin/bash

echo "=========================================="
echo " 🚀 Starting Contract Scanner AI (Mac/Linux)"
echo "=========================================="

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed. Please install Python 3.9+."
    exit 1
fi

VENV_DIR=".venv"

# 2. Check and Create Virtual Environment
if [ ! -d "$VENV_DIR" ]; then
    echo "👉 Creating virtual environment ($VENV_DIR)..."
    python3 -m venv $VENV_DIR
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
echo "🌐 PC Dashboard: http://localhost:8080/admin.html"
echo "📱 Mobile Scanner: http://localhost:8080"
echo "   (Use ADB reverse to access via USB: adb reverse tcp:8080 tcp:8080)"
echo "------------------------------------------"
echo "🚀 Server is running. Press Ctrl+C to stop."
python3 server.py

#!/usr/bin/env bash
# ParkWatch Server — Linux Install Script
set -e

echo "============================================"
echo "  ParkWatch Server Installer (Linux)"
echo "============================================"
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "[*] Installing Python 3..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip python3-venv
else
    echo "[✓] Python 3 found: $(python3 --version)"
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "[*] Creating virtual environment..."
    python3 -m venv venv
else
    echo "[✓] Virtual environment already exists."
fi

# Activate and install deps
echo "[*] Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "============================================"
echo "  Installation complete!"
echo "============================================"
echo ""
echo "  To run the server:"
echo ""
echo "    source venv/bin/activate"
echo "    python app.py"
echo ""
echo "  Server will start on http://0.0.0.0:2026"
echo "============================================"

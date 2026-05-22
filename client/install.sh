#!/usr/bin/env bash
# ParkWatch Client — DietPi Install Script
# For Raspberry Pi Zero 2 W running DietPi (headless, no GUI)
set -e

echo "============================================"
echo "  ParkWatch Client Installer (DietPi)"
echo "============================================"
echo ""

# Update packages
echo "[*] Updating package lists..."
sudo apt-get update

# Install system dependencies
echo "[*] Installing system dependencies..."
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    tesseract-ocr \
    tesseract-ocr-ron \
    tesseract-ocr-eng \
    libopencv-dev \
    python3-opencv \
    libatlas-base-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    v4l-utils

echo "[✓] System dependencies installed."

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "[*] Creating virtual environment..."
    python3 -m venv venv --system-site-packages
else
    echo "[✓] Virtual environment already exists."
fi

# Install Python dependencies
echo "[*] Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create captures directory
mkdir -p captures

# Create systemd service for auto-start
echo "[*] Setting up systemd service..."
INSTALL_DIR=$(pwd)
SERVICE_FILE="/etc/systemd/system/parkwatch.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=ParkWatch Parking Monitor Client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/main.py
Restart=always
RestartSec=30
Environment="PARKWATCH_SERVER=http://YOUR_SERVER_IP:2026"

[Install]
WantedBy=multi-user.target
EOF

echo "[✓] Systemd service created at ${SERVICE_FILE}"
echo ""
echo "============================================"
echo "  Installation complete!"
echo "============================================"
echo ""
echo "  BEFORE STARTING: Edit the server URL:"
echo ""
echo "    sudo nano /etc/systemd/system/parkwatch.service"
echo "    # Change YOUR_SERVER_IP to your server's IP"
echo ""
echo "  Then enable and start the service:"
echo ""
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable parkwatch"
echo "    sudo systemctl start parkwatch"
echo ""
echo "  Or run manually:"
echo ""
echo "    source venv/bin/activate"
echo "    PARKWATCH_SERVER=http://YOUR_SERVER_IP:2026 python main.py"
echo ""
echo "  Health check: http://localhost:3000/"
echo "============================================"

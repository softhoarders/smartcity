#!/usr/bin/env bash
# ParkWatch Client — Raspberry Pi Zero / DietPi installer
# Headless capture every ~12 min (day) with energy-saving defaults and boot autostart.
set -euo pipefail

echo "============================================"
echo "  ParkWatch Client Installer (Raspberry Pi)"
echo "============================================"
echo ""

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${SUDO_USER:-$(whoami)}"
ENV_FILE="/etc/default/parkwatch"
SERVICE_FILE="/etc/systemd/system/parkwatch.service"

is_raspberry_pi() {
    [ -f /etc/rpi-issue ] || grep -qiE 'raspberry|bcm2835' /proc/cpuinfo 2>/dev/null
}

read -r -p "ParkWatch server URL [http://YOUR_SERVER_IP:2026]: " SERVER_URL
SERVER_URL="${SERVER_URL:-http://YOUR_SERVER_IP:2026}"

echo "[*] Updating package lists..."
sudo apt-get update -qq

APT_PACKAGES=(
    python3
    python3-pip
    python3-venv
    python3-numpy
    tesseract-ocr
    tesseract-ocr-ron
    tesseract-ocr-eng
    python3-opencv
    libjpeg-dev
    libpng-dev
    libtiff-dev
    v4l-utils
    iw
)

# libatlas-base-dev was removed in Debian Bookworm / recent Raspberry Pi OS.
if apt-cache show libopenblas-dev &>/dev/null; then
    APT_PACKAGES+=(libopenblas-dev)
elif apt-cache show libatlas-base-dev &>/dev/null; then
    APT_PACKAGES+=(libatlas-base-dev)
fi

echo "[*] Installing system dependencies..."
sudo apt-get install -y "${APT_PACKAGES[@]}"

if [ ! -d "${INSTALL_DIR}/venv" ]; then
    echo "[*] Creating virtual environment..."
    python3 -m venv "${INSTALL_DIR}/venv" --system-site-packages
else
    echo "[✓] Virtual environment already exists."
fi

echo "[*] Installing Python dependencies..."
# shellcheck disable=SC1091
source "${INSTALL_DIR}/venv/bin/activate"
pip install --upgrade pip -q

PIP_ARGS=()
if is_raspberry_pi; then
    echo "[*] Using piwheels for Raspberry Pi builds..."
    PIP_ARGS+=(--extra-index-url https://www.piwheels.org/simple)
    # Prefer apt python3-opencv / python3-numpy on Pi (especially Pi Zero).
    pip install "${PIP_ARGS[@]}" \
        pytesseract==0.3.13 \
        requests==2.32.3 \
        flask==3.1.1 \
        imutils==0.5.4 \
        -q
else
    pip install "${PIP_ARGS[@]}" -r "${INSTALL_DIR}/requirements.txt" -q
fi

mkdir -p "${INSTALL_DIR}/captures" "${INSTALL_DIR}/evidence"

echo "[*] Writing ${ENV_FILE}..."
sudo tee "${ENV_FILE}" > /dev/null <<EOF
# ParkWatch client environment (edit and restart: sudo systemctl restart parkwatch)
PARKWATCH_SERVER=${SERVER_URL}
PARKWATCH_ENERGY_SAVE=1
PARKWATCH_DAY_INTERVAL=720
PARKWATCH_NIGHT_INTERVAL=1200
PARKWATCH_CAMERA=0
PARKWATCH_CAPTURE_WIDTH=1280
PARKWATCH_CAPTURE_HEIGHT=720
EOF
sudo chmod 644 "${ENV_FILE}"

echo "[*] Applying one-time power optimizations..."
PARKWATCH_ENERGY_SAVE=1 "${INSTALL_DIR}/venv/bin/python" -c "from power_manager import apply_install_defaults; apply_install_defaults()" || true

echo "[*] Installing systemd service (starts on boot)..."
sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=ParkWatch Parking Monitor Client
After=network-online.target local-fs.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=-${ENV_FILE}
ExecStartPre=/bin/sleep 15
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/main.py
Restart=always
RestartSec=45
Nice=5
IOSchedulingClass=idle
SupplementaryGroups=video

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable parkwatch.service
echo "[*] Starting parkwatch.service..."
sudo systemctl restart parkwatch.service || true

echo ""
echo "============================================"
echo "  Installation complete"
echo "============================================"
echo ""
echo "  Config:  sudo nano ${ENV_FILE}"
echo "  Status:  sudo systemctl status parkwatch"
echo "  Logs:    journalctl -u parkwatch -f"
echo "  Health:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):3000/"
echo ""
echo "  Service is enabled — it will start automatically after reboot."
echo "============================================"

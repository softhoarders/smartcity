# Deployment Guide

This guide covers the current local/server deployment shape used by the project.

## Server Deployment

### Linux Quick Install

```bash
cd server
./install.sh
source venv/bin/activate
python app.py
```

The app listens on:

```text
http://0.0.0.0:2026
```

### Windows Quick Install

```powershell
cd server
.\install.ps1
.\venv\Scripts\Activate.ps1
python app.py
```

### Manual Install

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

If imports fail, install optional/runtime packages used by the code:

```bash
pip install python-dotenv pywebpush requests opencv-python-headless numpy ecdsa
```

### Production Server Process

The current `app.py` starts the Flask development server with `debug=True`. For production, use a WSGI server and disable debug mode.

Example:

```bash
pip install gunicorn
gunicorn -w 1 -b 0.0.0.0:2026 app:app
```

Use one worker with SQLite and in-process SSE/background queues. If using multiple workers, move realtime messages and background jobs to external services.

### Reverse Proxy And HTTPS

Use Nginx, Caddy, Apache, or a platform load balancer in front of the Flask app for:

- TLS termination.
- Static file caching.
- Request size limits for uploads.
- Access logs.
- Security headers.

HTTPS is required for production-grade browser push and secure login cookies.

## Server Configuration

Set environment variables before starting the server:

```bash
export PARKWATCH_SECRET="long-random-secret"
export PARKWATCH_ADMIN_USER="admin@example.com"
export PARKWATCH_ADMIN_HASH="bcrypt-hash"
export PARKWATCH_ADMIN_SIGNUP_CODE="private-code"
```

Mail:

```bash
export MAIL_SERVER="smtp.example.com"
export MAIL_PORT="587"
export MAIL_USE_TLS="true"
export MAIL_USERNAME="smtp-user"
export MAIL_PASSWORD="smtp-password"
export MAIL_DEFAULT_SENDER="noreply@example.com"
```

Web push:

```bash
export VAPID_PRIVATE_KEY="..."
export VAPID_PUBLIC_KEY="..."
export VAPID_SUBJECT="mailto:admin@example.com"
```

## Generate Admin Password Hash

Use Flask-Bcrypt or a small Python snippet inside the server environment:

```bash
python - <<'PY'
from flask_bcrypt import Bcrypt
bcrypt = Bcrypt()
print(bcrypt.generate_password_hash("replace-this-password").decode("utf-8"))
PY
```

Set the output as `PARKWATCH_ADMIN_HASH`.

## Generate VAPID Keys

```bash
cd server
source venv/bin/activate
pip install ecdsa
python generate_vapid.py
```

The script appends values to `server/.env`.

## Client Deployment

### Raspberry Pi Zero / DietPi Install

```bash
cd client
chmod +x install.sh
./install.sh
```

The installer:

- Installs OS packages (`python3-opencv`, `python3-numpy`, Tesseract, and related libs).
- Uses `libopenblas-dev` on Bookworm+ (replaces removed `libatlas-base-dev`).
- Creates a Python virtual environment with system site packages.
- Installs remaining Python dependencies via [piwheels](https://www.piwheels.org/) on Raspberry Pi.
- Creates `captures/` and `evidence/`.
- Writes `/etc/default/parkwatch` and `/etc/systemd/system/parkwatch.service`.

Edit the service:

```bash
sudo nano /etc/systemd/system/parkwatch.service
```

Set:

```text
Environment="PARKWATCH_SERVER=http://SERVER_IP:2026"
```

Start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable parkwatch
sudo systemctl start parkwatch
```

View logs:

```bash
journalctl -u parkwatch -f
```

### Manual Client Run

```bash
cd client
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
PARKWATCH_SERVER=http://SERVER_IP:2026 python main.py
```

### Camera Setup

Check camera availability:

```bash
v4l2-ctl --list-devices
```

If the camera is not index `0`, set:

```bash
export PARKWATCH_CAMERA="1"
```

### Test Image Mode

```bash
PARKWATCH_SERVER=http://SERVER_IP:2026 \
PARKWATCH_TEST_IMAGE=/absolute/path/to/test.jpg \
python main.py
```

## Network Requirements

Client to server:

- TCP `2026` for API calls.

Browser to server:

- TCP `2026` or reverse proxy HTTPS port.

Client health endpoint:

- TCP `3000` if you want to inspect client status directly.

Optional local server dependencies:

- Ollama on `localhost:11434`.
- SMTP server as configured.

## First Deployment Checklist

1. Start the server.
2. Log in as admin.
3. Start one client.
4. Confirm the device appears in the dashboard.
5. Assign the device name, spot label, and plate.
6. Confirm the client starts capturing on its next cycle.
7. Test with `PARKWATCH_TEST_IMAGE` before relying on live camera OCR.
8. Register a driver account.
9. Approve the driver's plate proof.
10. Trigger a mismatch and confirm the fine appears in the admin dashboard and driver portal.


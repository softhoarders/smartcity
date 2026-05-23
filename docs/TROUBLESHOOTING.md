# Troubleshooting

## Server Will Not Start

### Missing Python Package

Symptom:

```text
ModuleNotFoundError
```

Fix:

```bash
cd server
source venv/bin/activate
pip install -r requirements.txt
pip install python-dotenv pywebpush requests opencv-python-headless numpy ecdsa
```

### Port 2026 Already In Use

Find the process:

```bash
lsof -i :2026
```

Stop it or change `PORT` in `server/config.py`.

### Database Error

Back up and recreate local development database:

```bash
cd server
mv parkwatch.db parkwatch.db.backup
python app.py
```

Do not delete a production database without a verified backup.

## Cannot Log In As Admin

Use the unified login page:

```text
/login
```

Select Admin account type.

Local test credentials:

- Email: `admin`
- Password: `admin123!`

If using configured admin credentials, confirm:

- `PARKWATCH_ADMIN_USER`
- `PARKWATCH_ADMIN_HASH`

## Client Install Fails on Raspberry Pi

### `libatlas-base-dev` has no installation candidate

This package was removed in Debian Bookworm and recent Raspberry Pi OS. Use the current `client/install.sh`, which installs `libopenblas-dev` instead and pulls OpenCV/NumPy from apt on the Pi.

```bash
cd client
git pull
./install.sh
```

### `pip` fails building OpenCV or NumPy on Pi Zero

The installer uses apt `python3-opencv` and `python3-numpy` with `--system-site-packages` and only pip-installs lightweight packages on Raspberry Pi. Ensure the Pi has network access to `piwheels.org`.

## Client Cannot Register

Check:

- Server is running.
- `PARKWATCH_SERVER` points to the correct host and port.
- Pi can reach the server:

```bash
curl http://SERVER_IP:2026/api/devices
```

If the server URL is wrong in systemd:

```bash
sudo nano /etc/systemd/system/parkwatch.service
sudo systemctl daemon-reload
sudo systemctl restart parkwatch
```

## Device Appears Offline

The server considers devices offline after 120 seconds without heartbeat.

The client default capture interval is 600 seconds during the day and 1800 seconds at night, so a healthy device may appear offline between cycles.

Fix options:

- Increase `OFFLINE_THRESHOLD_SECONDS` in `server/config.py`.
- Send heartbeats more frequently than capture cycles.

## Camera Does Not Open

Check camera devices:

```bash
v4l2-ctl --list-devices
```

Try another camera index:

```bash
PARKWATCH_CAMERA=1 python main.py
```

Make sure the service user has permission to access the camera.

## OCR Returns No Plate

Check:

- Tesseract is installed.
- Romanian and English language packs are installed.
- Image is sharp, well-lit, and not too angled.
- Plate occupies enough pixels.
- Camera resolution is set correctly.

Test Tesseract:

```bash
tesseract --list-langs
```

Expected languages include:

- `ron`
- `eng`

Use test image mode to isolate OCR from camera capture:

```bash
PARKWATCH_TEST_IMAGE=/absolute/path/to/test.jpg python main.py
```

## Weather Camera Adjustment Fails

`client/main.py` calls `requests.get()` in `_update_weather_camera_settings()` but does not import `requests`.

Fix:

```python
import requests
```

Add it near the other imports at the top of `client/main.py`.

## Fines Are Not Created

Check:

- Device has an assigned plate in admin UI.
- Client is detecting a different plate.
- Client can POST to `/api/fines`.
- Server has write access to `server/uploads/`.
- `detected_plate` is not empty.

The client skips capture if no plate is assigned and no immediate capture was requested.

## Push Notifications Do Not Work

Check:

- VAPID keys are configured.
- Browser has notification permission.
- User is logged in when subscribing.
- App is served over HTTPS in production.
- Service worker is registered.

Also confirm `GET /api/push/public-key` returns a non-empty `publicKey`.

## Email Evidence Is Not Sent

If using mock mode:

- Confirm files appear in `server/mail_queue/`.

If using SMTP:

- Confirm `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, and `MAIL_DEFAULT_SENDER`.
- Check server logs for mailer errors.
- Confirm `photo_requested=True` and `photo_sent_at` is empty before the worker runs.

## AI Appeal Review Fails

Check:

- Ollama is running on `localhost:11434`.
- Model `qwen3-vl:2b` is installed.
- Evidence image exists in `server/uploads/`.
- Server has `requests`, `opencv-python-headless`, and `numpy` installed.

Manual model check:

```bash
ollama list
```

## Static PWA Icons Missing

`manifest.json` and `sw.js` reference:

- `/static/icon-192x192.png`
- `/static/icon-512x512.png`
- `/static/badge-72x72.png`

If these files are absent, browsers may show missing icon warnings. Add the icon files or update the manifest/service worker paths.

## Git Push Access Cannot Be Confirmed

`smartcity-main` is not its own Git repository right now. It is untracked inside `/Users/thechallenger_/Downloads`, whose configured remotes point to unrelated repositories.

Fix:

1. Configure the correct SmartCity remote for this project.
2. Run a non-destructive push dry run against that remote.


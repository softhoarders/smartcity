# ParkWatch Client

Raspberry Pi / DietPi edge client: periodic 720p capture, license-plate OCR, server sync, and energy-aware operation.

## Features

- MAC-based device identity and auto-registration
- Heartbeats (Wi‑Fi, CPU temp, spot status)
- **720p** capture every **~12 min** (day) / **~20 min** (night), configurable
- Improved OCR: CLAHE preprocessing, multi-PSM Tesseract, confidence scoring
- **Energy saving**: CPU governor switching, HDMI off, Wi‑Fi power save, chunked idle sleep
- **systemd** service with **boot autostart** (`WantedBy=multi-user.target`)
- Health endpoint on port `3000`

## Quick install (DietPi / Raspberry Pi)

```bash
cd client
chmod +x install.sh
./install.sh
```

The installer writes `/etc/default/parkwatch`, enables `parkwatch.service`, and starts it. After a power loss, the Pi will start monitoring again once the network is up.

```bash
sudo systemctl status parkwatch
journalctl -u parkwatch -f
```

## Configuration (`/etc/default/parkwatch`)

| Variable | Default | Description |
|----------|---------|-------------|
| `PARKWATCH_SERVER` | — | Server base URL |
| `PARKWATCH_DAY_INTERVAL` | `720` | Seconds between captures (day) |
| `PARKWATCH_NIGHT_INTERVAL` | `1200` | Seconds between captures (night) |
| `PARKWATCH_ENERGY_SAVE` | `1` | `0` to disable Pi power tuning |
| `PARKWATCH_CAMERA` | `0` | V4L2 camera index |
| `PARKWATCH_TEST_IMAGE` | — | Use a static image instead of camera |

After editing: `sudo systemctl restart parkwatch`

## Files

```text
client/
  main.py            Monitoring loop + health server
  power_manager.py   DietPi / Pi energy profiles
  plate_reader.py    Plate detection + OCR
  camera.py          720p capture (minimal warm-up)
  communicator.py    REST API client
  config.py          Settings from environment
  install.sh         apt deps, venv, systemd, autostart
```

## Development (no camera)

```bash
cd client
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
PARKWATCH_SERVER=http://127.0.0.1:2026 \
PARKWATCH_TEST_IMAGE=/path/to/plate.jpg \
PARKWATCH_ENERGY_SAVE=0 \
python main.py
```

## Health check

`GET http://<pi-ip>:3000/` — returns status, MAC, last capture, last plate, cycle count.

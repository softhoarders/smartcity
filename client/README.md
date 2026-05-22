# ParkWatch Client

The client is the Raspberry Pi parking monitor. It registers with the server, exposes a health endpoint, captures images, reads plates with OCR, compares the detected plate to the assigned plate, and reports mismatches.

## Responsibilities

- Identify the device by MAC address.
- Register with the server.
- Send heartbeats with Wi-Fi, CPU temperature, and parking spot status.
- Fetch the assigned plate and spot metadata from the server.
- Capture images from a USB camera or a configured test image.
- Detect license plates with OpenCV and Tesseract.
- Track how long a mismatched plate has been present.
- Save local evidence for mismatches.
- Upload fine reports and evidence images to the server.
- Expose a lightweight health endpoint on port `3000`.

## Files

```text
client/
  main.py            Main monitoring loop and health endpoint.
  communicator.py    REST client for server communication.
  camera.py          Camera capture and capture cleanup.
  plate_reader.py    Plate detection, OCR, normalization, and scoring.
  config.py          Server URL, camera, OCR, schedule, and path settings.
  requirements.txt   Python dependencies.
  install.sh         DietPi/Raspberry Pi installer and systemd service setup.
```

## Requirements

- Raspberry Pi Zero 2 W or similar Linux device.
- USB camera available through OpenCV.
- Python 3.
- Tesseract OCR with Romanian and English language packs.
- Network access to the ParkWatch server.

The install script installs common DietPi/Raspberry Pi packages:

- `python3`
- `python3-pip`
- `python3-venv`
- `tesseract-ocr`
- `tesseract-ocr-ron`
- `tesseract-ocr-eng`
- `libopencv-dev`
- `python3-opencv`
- `v4l-utils`

## Install On Raspberry Pi / DietPi

```bash
cd client
./install.sh
```

Then edit the generated systemd service:

```bash
sudo nano /etc/systemd/system/parkwatch.service
```

Replace `YOUR_SERVER_IP` with the server address:

```text
Environment="PARKWATCH_SERVER=http://YOUR_SERVER_IP:2026"
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable parkwatch
sudo systemctl start parkwatch
```

Check status:

```bash
sudo systemctl status parkwatch
journalctl -u parkwatch -f
```

## Manual Run

```bash
cd client
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
PARKWATCH_SERVER=http://SERVER_IP:2026 python main.py
```

## Development With A Test Image

Use a static image instead of a physical camera:

```bash
PARKWATCH_SERVER=http://localhost:2026 \
PARKWATCH_TEST_IMAGE=/absolute/path/to/test-plate.jpg \
python main.py
```

The test image is copied into `client/captures/` for each cycle.

## Environment Variables

- `PARKWATCH_SERVER`: server base URL. Default: `http://localhost:2026`.
- `PARKWATCH_CAMERA`: OpenCV camera index. Default: `0`.
- `PARKWATCH_TEST_IMAGE`: absolute path to a static test image. Default: disabled.

## Health Endpoint

The client exposes:

```text
GET http://CLIENT_IP:3000/
```

Response fields include:

- `service`
- `status`
- `mac_address`
- `last_capture`
- `last_detected_plate`
- `assigned_plate`
- `cycle_count`
- `uptime`

## Monitoring Cycle

1. Resolve MAC address from Linux network interfaces or `uuid.getnode()`.
2. Start the health server.
3. Register with the server.
4. Send a heartbeat.
5. Fetch the assigned plate.
6. Capture an image if a plate is assigned or the server requested immediate capture.
7. Run OCR and normalize the detected plate.
8. Compare detected and assigned plates.
9. If mismatched, save local evidence and report a fine.
10. Delete temporary captures and periodically clean old captures/evidence.
11. Sleep based on day/night schedule.

## Scheduling

Configured in `config.py`:

- Day mode: `06:00` through `21:59`.
- Day interval: `600` seconds.
- Night interval: `1800` seconds.

## Plate OCR

The OCR pipeline:

- Loads and resizes the image.
- Converts to grayscale.
- Applies bilateral filtering.
- Uses Canny edge detection and contour filtering.
- Falls back to morphological detection if contour detection fails.
- Crops candidate plate regions.
- Uses Tesseract with a letters-and-digits whitelist.
- Normalizes likely Romanian formats such as `B 123 ABC` and `CJ 01 XYZ`.
- Scores candidates and returns the best plate and confidence score.

## Known Implementation Note

`main.py` calls `requests.get()` in `_update_weather_camera_settings()` but does not currently import `requests`. Add `import requests` near the top of `main.py` if weather-based camera adjustment is used.


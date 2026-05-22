# ParkWatch / ParkScan Smart City Parking Monitor

ParkWatch is a smart parking monitoring system with two deployable parts:

- `server/`: a Flask web application for administrators and drivers.
- `client/`: a Raspberry Pi parking-spot monitor that captures vehicle images, reads license plates, and reports mismatches.

The user-facing web product is branded as ParkScan in the templates and PWA metadata. The code and services use the ParkWatch name in several places.

## What It Does

- Registers parking-monitoring devices by MAC address.
- Lets admins assign each device to a parking spot and expected license plate.
- Runs a Raspberry Pi client loop that captures images from a USB camera.
- Uses OpenCV and Tesseract OCR to detect Romanian/EU-style license plates.
- Reports parking mismatches to the server with evidence images.
- Provides an admin dashboard for device status, spot assignment, fines, driver verification, and appeals.
- Provides a driver portal for plate-owner verification, alerts, photo evidence requests, appeals, and receipts.
- Supports web push notifications when VAPID keys are configured.
- Supports email delivery of requested evidence photos, with a local mock-mail mode for development.
- Supports optional local Ollama vision review for fine appeals.

## Project Layout

```text
smartcity-main/
  client/
    main.py              Raspberry Pi monitoring loop and health endpoint.
    communicator.py      REST client for server registration, heartbeat, config, and fine reporting.
    camera.py            USB camera capture and local capture cleanup.
    plate_reader.py      OpenCV/Tesseract plate detection and OCR pipeline.
    config.py            Client ports, camera settings, scheduling, paths, and test mode.
    requirements.txt     Python dependencies for the Pi client.
    install.sh           DietPi/Raspberry Pi installer and systemd setup.
  server/
    app.py               Flask app, API routes, portals, push, appeals, and SSE.
    models.py            SQLAlchemy models for devices, fines, users, messages, and push subscriptions.
    mailer.py            Background worker for evidence-photo email delivery.
    config.py            Server settings, admin credentials, mail, database, and upload paths.
    generate_vapid.py    Helper to generate web-push VAPID keys.
    requirements.txt     Python dependencies for the server.
    install.sh           Linux server installer.
    install.ps1          Windows server installer.
    templates/           Admin and driver HTML views.
    static/              CSS, PWA manifest, service worker, and images.
  docs/
    README.md            Documentation index.
    ARCHITECTURE.md      Component and data-flow overview.
    API.md               HTTP endpoints and payloads.
    DEPLOYMENT.md        Server and client deployment instructions.
    OPERATIONS.md        Day-to-day operations and maintenance.
    DATA_MODEL.md        Database model reference.
    SECURITY.md          Security notes and production hardening.
    TROUBLESHOOTING.md   Common issues and fixes.
```

## Quick Start: Server

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open `http://localhost:2026`.

Default local admin sign-in is available through the unified login page:

- Account type: Admin
- Email: `admin`
- Password: `admin123!`

For real deployments, replace the default admin credentials and secret values before exposing the server.

## Quick Start: Client

```bash
cd client
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
PARKWATCH_SERVER=http://SERVER_IP:2026 python main.py
```

The client exposes a health endpoint at `http://localhost:3000/`.

For development without a camera:

```bash
PARKWATCH_SERVER=http://localhost:2026 \
PARKWATCH_TEST_IMAGE=/absolute/path/to/test-plate.jpg \
python main.py
```

## Typical Workflow

1. Start the server.
2. Start a client device.
3. The client registers itself with `/api/devices/register`.
4. An admin opens the dashboard and assigns a parking spot label and expected plate to the device.
5. The client fetches its assigned plate, captures images, reads plates, and reports mismatches.
6. Drivers create accounts, upload plate ownership proof, and wait for admin verification.
7. Verified drivers can see fines connected to their plate, request photo evidence, and appeal.

## Important Runtime Files

These files are created or modified while the app runs and should normally be treated as local state:

- `server/parkwatch.db`
- `server/uploads/`
- `server/mail_queue/`
- `server/.env`
- `server/server_error.log`
- `client/captures/`
- `client/evidence/`
- `client/client_error.log`
- Python `__pycache__/` directories

## Configuration

Server settings are read from environment variables in `server/config.py`:

- `PARKWATCH_SECRET`
- `PARKWATCH_ADMIN_USER`
- `PARKWATCH_ADMIN_HASH`
- `PARKWATCH_ADMIN_SIGNUP_CODE`
- `MAIL_SERVER`
- `MAIL_PORT`
- `MAIL_USE_TLS`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_DEFAULT_SENDER`

Web push settings are read in `server/app.py`:

- `VAPID_PRIVATE_KEY`
- `VAPID_PUBLIC_KEY`
- `VAPID_SUBJECT`

Client settings are read from environment variables in `client/config.py`:

- `PARKWATCH_SERVER`
- `PARKWATCH_CAMERA`
- `PARKWATCH_TEST_IMAGE`

## Documentation

Start with [docs/README.md](docs/README.md).

## Git And Push Access Status

This folder is not currently its own Git repository. It is an untracked directory inside a larger repository rooted at `/Users/thechallenger_/Downloads`, and that parent repository has remotes for unrelated projects. Because of that, push access for a dedicated SmartCity repository cannot be confirmed from the current checkout.

To make this project independently pushable, initialize or clone the correct SmartCity repository into `smartcity-main`, then set the correct remote:

```bash
git init
git remote add origin https://github.com/OWNER/REPOSITORY.git
git status
```

After the correct remote is configured, push access can be checked with a non-destructive dry run against that remote.


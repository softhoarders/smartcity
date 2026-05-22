# ParkWatch Server

The server is a Flask application that manages parking devices, driver accounts, fines, appeals, web push notifications, email evidence delivery, and admin dashboards.

## Responsibilities

- Register and track Raspberry Pi devices by MAC address.
- Store device status, assigned parking spot labels, and assigned license plates.
- Receive fine reports from clients with optional evidence images.
- Provide the admin dashboard at `/admin`.
- Provide the driver portal at `/portal`.
- Verify driver plate ownership proof.
- Send web push alerts when unauthorized parking is reported.
- Send requested photo evidence by email or local mock mail.
- Run optional local AI-assisted appeal review through Ollama.
- Broadcast real-time updates with server-sent events at `/stream`.

## Files

```text
server/
  app.py               Main Flask app and route definitions.
  models.py            SQLAlchemy database models.
  config.py            Runtime configuration and defaults.
  mailer.py            Background email worker for requested evidence photos.
  generate_vapid.py    VAPID key generator for browser push notifications.
  terminal_config.yaml Lightweight local terminal configuration.
  requirements.txt     Server Python dependencies.
  install.sh           Linux install helper.
  install.ps1          Windows install helper.
  templates/           Jinja templates for admin and driver screens.
  static/              CSS, service worker, PWA manifest, and images.
```

## Requirements

- Python 3.10+ recommended.
- SQLite for local persistence.
- Optional SMTP server for real email.
- Optional Ollama running locally with `qwen3-vl:2b` for AI appeal analysis.
- Optional VAPID keys for web push.

The code also imports packages that are not listed in `server/requirements.txt` today:

- `python-dotenv`
- `pywebpush`
- `requests`
- `opencv-python` or `opencv-python-headless`
- `numpy`
- `ecdsa` for `generate_vapid.py`

Install these manually if the server fails at import time or if you use the related features.

## Install

Linux:

```bash
cd server
./install.sh
source venv/bin/activate
python app.py
```

Manual:

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Windows PowerShell:

```powershell
cd server
.\install.ps1
.\venv\Scripts\Activate.ps1
python app.py
```

## Run

```bash
cd server
source venv/bin/activate
python app.py
```

The server listens on `http://0.0.0.0:2026`.

## Login

The unified login page is `/login`.

Local test admin:

- Account type: Admin
- Email: `admin`
- Password: `admin123!`

Configured admin:

- Email defaults to `admin`, controlled by `PARKWATCH_ADMIN_USER`.
- Password hash defaults to the value in `config.py`, controlled by `PARKWATCH_ADMIN_HASH`.

Admin signup requires `PARKWATCH_ADMIN_SIGNUP_CODE`.

## Environment Variables

For local use, copy `.env.example` to `.env` or use the generated local `.env` file in this folder. The real `.env` is intentionally ignored by Git because it contains secrets and VAPID private keys.

```bash
export PARKWATCH_SECRET="replace-with-a-long-random-secret"
export PARKWATCH_ADMIN_USER="admin@example.com"
export PARKWATCH_ADMIN_HASH="bcrypt-hash"
export PARKWATCH_ADMIN_SIGNUP_CODE="private-invite-code"

export MAIL_SERVER="smtp.example.com"
export MAIL_PORT="587"
export MAIL_USE_TLS="true"
export MAIL_USERNAME="smtp-user"
export MAIL_PASSWORD="smtp-password"
export MAIL_DEFAULT_SENDER="noreply@example.com"

export VAPID_PRIVATE_KEY="..."
export VAPID_PUBLIC_KEY="..."
export VAPID_SUBJECT="mailto:admin@example.com"
```

If `MAIL_SERVER=localhost`, the mailer writes mock email files to `server/mail_queue/`.

## Generate Web Push Keys

```bash
cd server
source venv/bin/activate
python generate_vapid.py
```

This appends VAPID settings to `server/.env`.

## Database

The app uses SQLite at `server/parkwatch.db`.

On startup, `db.create_all()` creates missing tables. The app also adds legacy-migration columns to the `users` table if they are missing.

Back up `parkwatch.db` before deployments or schema changes.

## Uploads And Evidence

Evidence and verification files are saved under `server/uploads/`.

The app periodically deletes uploaded files older than 30 days. Fine database records may still reference deleted files after cleanup, so tune retention based on legal and product requirements.

## Main Pages

- `/login`: driver/admin sign-in and signup.
- `/admin`: admin dashboard.
- `/device/<id>`: device detail and configuration.
- `/fines`: all fine records.
- `/portal`: driver portal.
- `/portal/fine/<id>/receipt`: printable resolution receipt.
- `/terminal/login`: lightweight local terminal login.
- `/terminal`: authenticated terminal-style command runner.

## Local Terminal

The server includes a very small terminal-style admin page controlled by `terminal_config.yaml`.

Default credentials:

- Username: `admin`
- Password: `admin123!`

Security controls:

- Enabled/disabled by YAML.
- Loopback-only by default, so only local requests from `127.0.0.1` or `::1` are allowed.
- Separate terminal session flag from the main Flask-Login admin session.
- CSRF token on command and logout forms.
- Commands start without a shell, so shell pipes, redirects, and command chaining are not interpreted.
- Interactive commands run through a PTY and render with xterm.js for lightweight TUI support.
- Commands run in a configured working directory under `server/`.
- Commands have a timeout and output cap.
- High-risk command names, shells, common interpreters, process-control tools, and protected system paths are blocked by config.

Change `terminal_config.yaml` before exposing this server beyond local development. Keeping the default password on a network-accessible server is not safe.

## Main APIs

- `POST /api/devices/register`
- `POST /api/devices/<mac>/heartbeat`
- `GET /api/devices/<mac>/config`
- `GET /api/devices`
- `POST /api/fines`
- `GET /api/fines`
- `PATCH /api/fines/<id>`
- `POST /api/users/register`
- `GET /api/push/public-key`
- `POST /api/push/subscribe`
- `GET /stream`

See [../docs/API.md](../docs/API.md) for payload details.

## Production Notes

- Disable Flask debug mode for production.
- Put the app behind a real WSGI server such as gunicorn or uWSGI.
- Use HTTPS if web push, authentication cookies, or external driver access are enabled.
- Replace default secrets and admin credentials.
- Move from SQLite to a managed database if multiple server processes or higher write volume are expected.
- Restrict access to evidence files and uploads.

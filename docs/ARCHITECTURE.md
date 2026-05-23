# Architecture

**Spotflow** (web app) and the **ParkWatch** backend are split into a server-side operations portal and one or more edge clients installed at parking spots.

## Components

```text
Raspberry Pi Client
  - Camera capture
  - OpenCV plate candidate detection
  - Tesseract OCR
  - Local evidence storage
  - Device heartbeat
  - Fine reporting

Flask Server
  - Admin dashboard
  - Driver portal
  - REST APIs
  - SQLite persistence
  - Evidence uploads
  - Push notification subscription and delivery
  - Email evidence worker
  - Optional Ollama appeal review

Browser Clients
  - Admin web UI
  - Driver web UI
  - PWA service worker for push notifications
```

## Data Flow

### Device Registration

1. Client derives its MAC address.
2. Client sends `POST /api/devices/register`.
3. Server creates or updates a `Device`.
4. Admin sees the device in the dashboard.
5. Admin assigns a spot label and expected plate.

### Normal Monitoring

1. Client sends `POST /api/devices/<mac>/heartbeat`.
2. Server updates `last_seen`, diagnostics, and spot status.
3. Client calls `GET /api/devices/<mac>/config`.
4. Client skips capture if no plate is assigned.
5. Client captures an image.
6. Client reads a plate locally.
7. Client compares detected plate to assigned plate.
8. Client reports mismatches with `POST /api/fines`.

### Fine Handling

1. Server stores a `Fine` and optional evidence image.
2. Server broadcasts an SSE `new_fine` event.
3. Server looks for a driver account matching the expected plate.
4. If a matching user exists and recent alerts have not been sent, server sends a web push notification.
5. Admin can resolve, reopen, or handle appeals.
6. Driver can request photo evidence and appeal.

### Evidence Email Flow

1. Driver clicks photo request.
2. Server marks `photo_requested=True`.
3. `PhotoMailerWorker` checks every 60 seconds.
4. Worker sends a real email or writes mock email to `mail_queue/`.
5. Worker sets `photo_sent_at`.

### Appeal Flow

1. Driver submits appeal text.
2. Server stores a `FineMessage`.
3. For first appeals, server may run local Ollama vision analysis.
4. AI can approve, reject, or escalate to human review.
5. A second appeal after AI rejection moves to human review.
6. Admin can approve or reject human-review appeals.

## Persistence

The server uses SQLite at `server/parkwatch.db`. SQLAlchemy models are defined in `server/models.py`.

Important persisted entities:

- Device
- Fine
- User
- FineMessage
- PushSubscription

## Realtime Updates

The server has an in-process list of queues for connected SSE clients. Updates are sent through `/stream` when devices update or fines are created/changed.

Because the queue list is in process memory, updates are not shared across multiple server processes. If the app is scaled horizontally, use a shared message broker.

## Background Work

The server starts two background threads on import/startup:

- `PhotoMailerWorker`: sends requested evidence photos.
- `periodic_cleanup`: deletes old uploaded files every day.

The server also starts short-lived appeal-analysis threads for some fines.

## External Services

- Tesseract: client OCR.
- Open-Meteo: optional client weather lookup for camera-mode decisions.
- SMTP: optional real email delivery.
- Web Push endpoints: browser push notification delivery.
- Ollama: optional local vision model for appeals.

## Deployment Shape

A typical deployment has:

- One server machine reachable by admins, drivers, and Pi clients.
- One SQLite database on the server machine.
- One or more Raspberry Pi clients on the same LAN or reachable network.
- HTTPS termination in front of the server for production.


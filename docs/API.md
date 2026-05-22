# API Reference

Base URL defaults to:

```text
http://SERVER_HOST:2026
```

Most device APIs do not require login. Browser portal routes use Flask-Login sessions.

## Devices

### Register Device

```http
POST /api/devices/register
Content-Type: application/json
```

Request:

```json
{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "name": "Optional Device Name"
}
```

Response `200`:

```json
{
  "id": 1,
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "name": "Pi-DDEEFF",
  "assigned_plate": null,
  "spot_label": "Unassigned Spot",
  "last_seen": "2026-05-20T10:30:00+00:00",
  "last_wifi": null,
  "last_temp": null,
  "capture_requested": false,
  "current_status": "empty",
  "is_online": true,
  "created_at": "2026-05-20T10:30:00+00:00"
}
```

Errors:

- `400`: missing `mac_address`.

### Device Heartbeat

```http
POST /api/devices/<mac>/heartbeat
Content-Type: application/json
```

Request:

```json
{
  "wifi_strength": 87,
  "temperature": 42.5,
  "spot_status": "empty"
}
```

`spot_status` values used by the client:

- `empty`
- `correct`
- `illegal`

Response `200`:

```json
{
  "status": "ok",
  "is_online": true,
  "action": null
}
```

If an admin requested immediate capture:

```json
{
  "status": "ok",
  "is_online": true,
  "action": "capture_now"
}
```

Errors:

- `404`: device not found.

### Get Device Config

```http
GET /api/devices/<mac>/config
```

Response `200`:

```json
{
  "assigned_plate": "B123ABC",
  "spot_label": "A-12",
  "name": "North Gate Camera"
}
```

Errors:

- `404`: device not found.

### List Devices

```http
GET /api/devices
```

Response `200`: array of device objects.

## Fines

### Report Fine

```http
POST /api/fines
Content-Type: multipart/form-data
```

Fields:

- `mac_address`: required.
- `detected_plate`: required.
- `expected_plate`: optional, falls back to assigned device plate.
- `first_seen`: optional ISO datetime.
- `duration_minutes`: optional integer, default `0`.
- `confidence_score`: optional float, default `0.0`.
- `image`: optional evidence image upload.

Response `201`:

```json
{
  "id": 10,
  "device_id": 1,
  "device_name": "North Gate Camera",
  "spot_label": "A-12",
  "detected_plate": "CJ01XYZ",
  "expected_plate": "B123ABC",
  "image_filename": "AA:BB:CC:DD:EE:FF_20260520_103000_capture.jpg",
  "first_seen": "2026-05-20T10:20:00",
  "last_seen": "2026-05-20T10:30:00+00:00",
  "duration_minutes": 10,
  "confidence_score": 82.0,
  "resolved": false,
  "photo_requested": false,
  "photo_sent_at": null,
  "appeal_status": "none",
  "appeal_reason": null,
  "created_at": "2026-05-20T10:30:00+00:00"
}
```

Appeal status is initialized from confidence:

- `< 60`: `pending_human`
- `60` through `< 80`: `pending_ai`
- `>= 80`: `none`

Errors:

- `400`: missing `mac_address` or `detected_plate`.
- `404`: device not found.

### List Fines

```http
GET /api/fines
```

Response `200`: array of fine objects, newest first.

### Update Fine

```http
PATCH /api/fines/<fine_id>
Content-Type: application/json
```

Request:

```json
{
  "resolved": true
}
```

Response `200`: updated fine object.

## Users

### Register Driver User By API

```http
POST /api/users/register
Content-Type: application/json
```

Request:

```json
{
  "email": "driver@example.com",
  "password": "long-password",
  "license_plate": "B123ABC",
  "name": "Driver Name"
}
```

Response `201`:

```json
{
  "status": "ok",
  "message": "User registered"
}
```

The API-created user starts with:

- `role="driver"`
- `verification_status="pending"`
- `verification_notes="Created through API; ownership proof still required."`

Errors:

- `400`: missing fields, invalid plate, duplicate email, or duplicate plate.

## Web Push

### Get Public Key

```http
GET /api/push/public-key
```

Response:

```json
{
  "publicKey": "..."
}
```

### Subscribe Current User

```http
POST /api/push/subscribe
Content-Type: application/json
```

Requires login.

Request body is the browser push subscription object.

Response `201`:

```json
{
  "status": "ok"
}
```

## Server-Sent Events

### Stream Updates

```http
GET /stream
Accept: text/event-stream
```

Requires login.

Events are sent as JSON payloads in `data:` lines:

```json
{
  "type": "device_update",
  "data": {}
}
```

Known event types:

- `device_update`
- `new_fine`
- `fine_updated`

## Browser Routes

### Public/Auth

- `GET /`: redirects based on login state.
- `GET|POST /login`: driver/admin sign-in and signup.
- `GET|POST /admin/login`: redirects to `/login?mode=admin`.
- `GET /logout`: logs out the current user.

### Admin

Requires admin login:

- `GET /admin`: dashboard.
- `GET /device/<device_id>`: device detail.
- `POST /device/<device_id>/update`: update name, spot label, and assigned plate.
- `POST /device/<device_id>/capture_now`: request capture on next heartbeat.
- `POST /device/<device_id>/delete`: delete device and its fines.
- `GET /fines`: all fines.
- `POST /fine/<fine_id>/resolve`: toggle resolved state.
- `POST /admin/users/<user_id>/verify/<approve|reject>`: approve or reject driver proof.
- `POST /admin/fine/<fine_id>/appeal/<approve|reject>`: handle human appeal.

### Driver

Requires driver login:

- `GET /portal`: driver fines and verification status.
- `POST /portal/fine/<fine_id>/request-photo`: request evidence email.
- `POST /portal/fine/<fine_id>/appeal`: submit appeal.
- `GET /portal/fine/<fine_id>/receipt`: printable receipt.

### Shared Authenticated

- `GET /uploads/<filename>`: serve uploaded evidence or proof files.
- `POST /fine/<fine_id>/chat`: add appeal chat message with optional attachment.


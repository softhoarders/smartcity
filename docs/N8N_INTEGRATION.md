# n8n integration for Spotflow

Spotflow stays thin: it **emits events** over HTTP webhooks. **n8n** owns notifications, waits, escalations, cron jobs, and third-party integrations.

## Best free approach

| Option | Cost | When to use |
|--------|------|-------------|
| **Self-hosted n8n (Docker)** | Free | **Recommended.** Unlimited workflows on your machine or VPS. |
| n8n Cloud free tier | Free | ~1,000 executions/month; fine for demos. |
| Paid n8n Cloud | Paid | Production without managing Docker. |

**Recommendation:** run n8n locally with Docker Compose:

```bash
docker compose -f docker-compose.n8n.yml up -d
```

Open the editor at [http://localhost:5678](http://localhost:5678), create a workflow with a **Webhook** node, path `spotflow`, method **POST**.

## Architecture

```
Pi camera / user action
  → Spotflow Flask server (SQLite)
    → POST webhook (async) → n8n
      → Email, Slack, Wait, HTTP Request back to Spotflow API, Sheets, etc.
```

Spotflow never blocks on n8n. Webhooks run in a background thread.

## Configure Spotflow

Add to `server/.env`:

```env
N8N_ENABLED=true
N8N_WEBHOOK_BASE_URL=http://localhost:5678/webhook
N8N_WEBHOOK_SECRET=your-hmac-secret
N8N_API_KEY=your-inbound-api-key
SPOTFLOW_PUBLIC_URL=http://127.0.0.1:2026
```

Restart the Flask server after changing `.env`.

### Webhook payload format

Every event is a JSON envelope:

```json
{
  "event_type": "violation.created",
  "timestamp": "2026-05-23T12:00:00+00:00",
  "source": "spotflow",
  "payload": { }
}
```

If `N8N_WEBHOOK_SECRET` is set, Spotflow sends header:

`X-Spotflow-Signature: sha256=<hmac-sha256 of raw body>`

In n8n, verify in a **Code** node if you need authenticity.

### Event types emitted

| event_type | When |
|------------|------|
| `violation.created` | Pi reports plate mismatch |
| `violation.resolved` | Admin or API resolves fine |
| `violation.appeal` | Driver or admin appeal action |
| `booking.requested` | New booking (pending approval) |
| `booking.approved` / `active` / `completed` / `rejected` | Status changes |
| `plate.verification` | Plate document approved or pending |
| `wallet.topup` / `wallet.subscription_*` | Wallet events |
| `waitlist.fulfilled` | Watchlist entry fulfilled (auto-book or notify-only complete) |
| `waitlist.failed` | Watchlist could not auto-book (e.g. insufficient balance) |
| `concierge.booked` | Driver confirmed a booking via AI concierge |

In n8n, add a **Switch** node on `{{ $json.event_type }}` to branch workflows.

## n8n → Spotflow API

n8n calls Spotflow with header:

`X-Spotflow-Api-Key: <N8N_API_KEY>`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/n8n/health` | Health check (no auth) |
| GET | `/api/n8n/fines/<id>` | Poll fine for Wait loops |
| GET | `/api/n8n/fines?unresolved=1` | List open violations |
| GET | `/api/n8n/bookings/<id>` | Booking status |
| POST | `/api/n8n/bookings/<id>/approve` | Auto-approve pending booking |
| GET | `/api/n8n/activity/summary?hours=24` | Demand signals input |
| POST | `/api/n8n/pricing/refresh-all` | Hourly smart pricing cron |
| GET | `/api/n8n/pricing/signals/<listing_id>` | Per-listing demand JSON |
| POST | `/api/n8n/subscriptions/process-renewals` | Monthly subscription cron |
| GET | `/api/n8n/subscribers` | Active subscribers |
| GET | `/api/n8n/report/weekly` | Monday admin report data |
| GET | `/api/n8n/devices/<id>/authorized-plate` | Camera authorization check |

Base URL: `http://127.0.0.1:2026` (or your deployed host).

## Example workflows

### 1. Violation escalation

1. **Webhook** `spotflow` (POST)
2. **IF** `event_type == violation.created`
3. **HTTP Request** → push/email to driver (your channel)
4. **Wait** 10 minutes
5. **HTTP Request** → `GET /api/n8n/fines/{{ fine_id }}`
6. **IF** `resolved == false` → send email with `photo_url`
7. **Wait** 20 minutes → notify admin if still open

### 2. Booking lifecycle

1. Switch on `booking.requested` → notify owner
2. Wait 30 min → `GET /api/n8n/bookings/:id`
3. If still `pending_approval` and `approval_mode == auto` → `POST .../approve`
4. On `booking.active` → `GET .../devices/:id/authorized-plate` (confirms renter plate for camera)

### 3. Plate verification

1. On `plate.verification` with `status: pending` → Slack to operators
2. On `status: approved` → email driver (n8n Send Email node)

Gemini verification still runs in Spotflow; n8n handles human queue + notifications.

### 4. Smart pricing (cron)

1. **Schedule Trigger** every hour
2. **HTTP Request** → `POST /api/n8n/pricing/refresh-all`
3. Optional: OpenWeatherMap node → merge weather in Code node → custom logic

### 5. Subscriptions (cron)

1. **Schedule Trigger** 1st of month (or daily)
2. **HTTP Request** → `POST /api/n8n/subscriptions/process-renewals`
3. **HTTP Request** → `GET /api/n8n/subscribers` → loop Send Email

### 6. Weekly admin report

1. **Cron** Monday 08:00 Europe/Bucharest
2. **HTTP Request** → `GET /api/n8n/report/weekly`
3. Format in **Code** node → Email / Slack

## Security (built into Spotflow)

- **Login rate limiting** — 8 attempts per 15 minutes per IP (configurable).
- **Security headers** — `X-Content-Type-Options`, `X-Frame-Options`, etc.
- **Webhook HMAC** — `N8N_WEBHOOK_SECRET` signs outbound events.
- **Inbound n8n API key** — `N8N_API_KEY` required for automation endpoints.
- **Simulated 2FA** — optional per-user; see below.

## Simulated 2FA

This is **not** real SMS/TOTP hardware. It demonstrates the login flow without external services.

1. Sign in → **Account** → **Enable simulated 2FA**
2. A 6-digit code appears on Account (refreshes every 30 seconds)
3. Sign out and sign in again → after password, enter that code on `/login/2fa`

The verify page also shows the current code when `SIMULATED_2FA_SHOW_CODE=true` (default).

Demo and built-in admin accounts (`id` 0, demo users) skip 2FA.

## Quick start checklist

1. `docker compose -f docker-compose.n8n.yml up -d`
2. Create n8n workflow: Webhook path `spotflow`
3. Copy webhook URL to `N8N_WEBHOOK_BASE_URL` in `server/.env`
4. Set `N8N_ENABLED=true`, generate `N8N_WEBHOOK_SECRET` and `N8N_API_KEY`
5. Restart Spotflow (`python app.py` or your process manager)
6. Trigger a test violation or booking → check n8n execution history

See also [SECURITY.md](./SECURITY.md) for production hardening.

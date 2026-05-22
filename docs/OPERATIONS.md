# Operations Guide

## Admin Workflow

1. Sign in at `/login` as an admin.
2. Open `/admin`.
3. Watch device status in the parking map.
4. For each new device, open the device detail page.
5. Set a human-readable device name.
6. Set the parking spot label.
7. Set the assigned license plate.
8. Save configuration.
9. Review pending driver plate verification requests.
10. Review active fines and appeals.

## Driver Workflow

1. Open `/login`.
2. Create a driver account.
3. Enter the license plate.
4. Upload proof such as registration, insurance, or ownership document.
5. Wait for admin approval.
6. After approval, use `/portal` to see parking activity connected to the plate.
7. Request photo evidence when needed.
8. Submit appeals from the portal.
9. Download or print receipts for resolved records.

## Device Lifecycle

### Registration

Devices register automatically when `client/main.py` starts.

The server uses the MAC address as the stable identifier. A restarted device with the same MAC updates the existing record.

### Online Status

A device is online when its `last_seen` timestamp is within `OFFLINE_THRESHOLD_SECONDS`, currently `120` seconds.

The client normally sends heartbeat once per monitoring cycle. With the default day interval of 10 minutes, devices may appear offline between cycles unless the heartbeat interval is made shorter than the server offline threshold.

### Spot Status

The client reports:

- `empty`: no plate detected.
- `correct`: detected plate matches assigned plate.
- `illegal`: detected plate does not match assigned plate.

### Immediate Capture

Admins can request immediate capture from the device detail page. The server sets `capture_requested=True`. The next heartbeat returns `action="capture_now"` and clears the flag.

## Fine Lifecycle

1. Client reports mismatch.
2. Server creates a fine.
3. Fine appears in admin UI.
4. Driver may receive a push alert if subscribed and linked to the expected plate.
5. Driver may request photo evidence.
6. Driver may appeal.
7. AI or admin reviews the appeal.
8. Admin or AI resolves or rejects.
9. Driver can print a receipt if resolved.

## Logs

Server:

- Terminal output from `python app.py`.
- `server/server_error.log` if used by local runs.
- `server/mail_queue/` for mock email output.

Client:

- Terminal output from `python main.py`.
- `client/client_error.log` if used by local runs.
- `journalctl -u parkwatch -f` when running as systemd.

## Backups

Back up:

- `server/parkwatch.db`
- `server/uploads/`
- `server/.env`

Suggested local backup:

```bash
cd server
sqlite3 parkwatch.db ".backup 'backup-parkwatch.db'"
tar -czf uploads-backup.tar.gz uploads
```

## Cleanup

Server:

- `periodic_cleanup()` removes upload files older than 30 days.

Client:

- `cleanup_old_captures()` keeps only the most recent 50 temporary captures.
- `cleanup_old_evidence(14)` removes local evidence older than 14 days.

Review these retention periods before production use.

## Monitoring Checks

Server:

- Can admins load `/admin`?
- Are new devices appearing?
- Are fines being created?
- Are uploads present in `server/uploads/`?
- Are mock or real emails being delivered?
- Are push subscriptions stored?

Client:

- Does `http://CLIENT_IP:3000/` return health JSON?
- Does the camera open?
- Does Tesseract read test images?
- Are heartbeats accepted?
- Is the assigned plate being fetched?
- Are local evidence files created only for mismatches?

## Common Maintenance Tasks

### Change Assigned Plate

1. Open admin dashboard.
2. Open the device detail page.
3. Update assigned license plate.
4. Save configuration.
5. Client picks up the new assignment on the next cycle.

### Retire Device

1. Open device detail.
2. Delete the device.
3. Stop and disable the Pi service:

```bash
sudo systemctl stop parkwatch
sudo systemctl disable parkwatch
```

Deleting a device also deletes its fines in the current implementation.

### Reset Local Development Database

Stop the server, then:

```bash
cd server
mv parkwatch.db parkwatch.db.backup
python app.py
```

The app creates a new database on startup.

### Use The Local Terminal

1. Start the server locally.
2. Open `/terminal/login` from the same machine.
3. Sign in with the credentials in `server/terminal_config.yaml`.
4. Run one command at a time.

By default the terminal only accepts loopback requests and runs commands from the server directory. Keep it that way unless there is a specific, controlled operational reason to expose it.

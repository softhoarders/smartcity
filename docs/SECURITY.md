# Security Notes

This project handles authentication, driver identity proof, plate data, and photographic evidence. Treat it as sensitive.

## Current Defaults To Change

Before any public or production deployment, change:

- `PARKWATCH_SECRET`
- `PARKWATCH_ADMIN_USER`
- `PARKWATCH_ADMIN_HASH`
- `PARKWATCH_ADMIN_SIGNUP_CODE`
- Mail credentials
- VAPID keys

The code includes a local test admin path with:

- Email: `admin`
- Password: `admin123!`

Remove or disable this before production.

## Authentication

The app uses Flask-Login sessions and bcrypt password hashes.

Recommendations:

- Enforce HTTPS.
- Set secure cookie settings in production.
- Remove hard-coded test login behavior.
- Rate-limit login and signup attempts.
- Add password reset flow only through a trusted email channel.

## Device API Trust

Device APIs are currently unauthenticated and trust the submitted MAC address.

Risks:

- A client can spoof another device MAC.
- Anyone with network access can register devices.
- Anyone with network access can report fake fines.

Recommended hardening:

- Issue per-device API tokens during provisioning.
- Require `Authorization: Bearer <token>` for device APIs.
- Sign heartbeat and fine-report payloads.
- Restrict device APIs to a private network or VPN.

## Local Terminal

The `/terminal` feature is intended for local development and emergency local administration.

Current safeguards:

- `server/terminal_config.yaml` can disable the feature.
- `loopback_only: true` blocks non-local requests by default.
- Login credentials are separate from normal driver/admin accounts.
- Command and logout forms require a session CSRF token.
- Commands start without `shell=True`, which prevents shell chaining, pipes, redirects, and expansion.
- Interactive commands run through a PTY and render with xterm.js in the browser.
- Command execution has a timeout and output limit.
- The first command token is checked against a configurable blocklist that includes deletion tools, process-control tools, shells, and common interpreters.
- Command arguments are checked against protected system paths.
- The working directory is constrained to the `server/` tree.

Important limitations:

- Any browser-accessible command runner is high risk.
- The default password `admin123!` is for local development only.
- Allowed commands can still read local files that the server process can read.
- Do not set `loopback_only: false` unless the server is protected by a trusted private tunnel, firewall, and strong credentials.

## Uploads

The server stores evidence, verification proof, and chat attachments in `server/uploads/`.

Current protections:

- Uses `secure_filename()` for uploaded fine and chat files.
- Restricts verification proof extensions to image/PDF formats.
- Requires login for `/uploads/<filename>`.

Recommended hardening:

- Add file size limits.
- Validate MIME type and content, not only extension.
- Store uploads outside the web app directory.
- Use randomized filenames for all uploads.
- Add per-object authorization checks so users can only access files linked to their own fines.
- Virus-scan uploads if accepting PDFs and user attachments.

## Evidence And Privacy

Photographs and license plates may be personal data depending on jurisdiction.

Recommended policies:

- Define retention duration for fine records and images.
- Log who accessed evidence.
- Document appeal and deletion workflows.
- Avoid sending evidence over unencrypted email unless legally acceptable.

## Web Push

Web push requires VAPID keys and HTTPS in most browser contexts.

Recommendations:

- Keep `VAPID_PRIVATE_KEY` secret.
- Rotate keys if leaked.
- Delete expired subscriptions.
- Avoid sensitive details in notification text.

## Email

If `MAIL_SERVER=localhost`, the app writes mock email text files to `server/mail_queue/`.

For real email:

- Use TLS.
- Store SMTP credentials in environment variables or a secret manager.
- Avoid attaching sensitive evidence unless policy allows it.
- Consider sending authenticated links instead of raw attachments.

## Local AI Appeal Review

The app sends evidence images to local Ollama at `http://localhost:11434/api/generate`.

Security posture:

- This is local-only by default.
- Do not point this to an external model endpoint unless evidence privacy has been reviewed.
- Treat AI results as assistance, not final authority, unless product/legal policy allows it.

## Database

SQLite is fine for local development and small single-process deployments.

Recommendations:

- Back up `parkwatch.db`.
- Restrict filesystem permissions.
- Move to PostgreSQL or another managed database for production.
- Use migrations instead of ad hoc schema changes.

## Production Checklist

- HTTPS enabled.
- Debug mode disabled.
- Default admin disabled.
- Strong secrets configured.
- Device authentication added.
- Upload size and type validation added.
- Evidence authorization tightened.
- Backup and retention policy in place.
- Logs reviewed for secret leakage.
- Correct Git remote configured before pushing.

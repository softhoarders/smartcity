# Server Templates

This directory contains the Jinja templates rendered by the Flask server.

## Files

- `base.html`: shared HTML shell, navigation, flash messages, CSS imports, PWA metadata, and Bootstrap script imports.
- `user_login.html`: unified sign-in and signup flow for drivers and admins.
- `admin_login.html`: legacy admin sign-in page that is currently bypassed by `/admin/login`, which redirects to the unified login page.
- `dashboard.html`: admin dashboard, parking map, verification queue, fine records, and live update hooks.
- `device_detail.html`: admin device configuration, diagnostics, immediate capture action, and device fine history.
- `user_portal.html`: driver-facing activity, verification status, evidence requests, appeals, and receipts.

## Rendering Context

The templates rely on Flask-Login's `current_user` and route-specific context values from `server/app.py`.

Common values:

- `devices`: list of registered devices.
- `fines`: list of fine records.
- `pending_users`: users awaiting plate proof review.
- `device`: selected device on the detail page.
- `show_all_fines`: dashboard mode flag for the all-fines page.

## Frontend Dependencies

`base.html` loads:

- Bootstrap CSS and JS from CDN.
- Inter font from Google Fonts.
- `server/static/style.css`.
- `server/static/manifest.json`.

## Notes

Keep route names in forms and links aligned with `server/app.py`. Most form actions use `url_for(...)`, so route renames should be made carefully.


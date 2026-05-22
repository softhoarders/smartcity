# Server Static Assets

This directory contains browser assets served by the Flask server.

## Files

- `style.css`: application styling for the admin dashboard, driver portal, authentication screens, tables, cards, parking map, and responsive layouts.
- `sw.js`: service worker push notification handler.
- `manifest.json`: PWA metadata for installable browser behavior.
- `city_traffic_bg.png`: traffic-themed background image.
- `images/traffic_bg.png`: additional traffic background image used by the UI.

## PWA And Push Assets

`manifest.json` references:

- `/static/icon-192x192.png`
- `/static/icon-512x512.png`

`sw.js` references:

- `/static/icon-192x192.png`
- `/static/badge-72x72.png`

Those icon files are not present in the current tree. Add them or update the paths before relying on polished PWA installation or push notification icons.

## Service Worker Behavior

`sw.js` listens for:

- `push`: shows a browser notification using the incoming payload.
- `notificationclick`: closes the notification and opens `/`.

Push notifications require server-side VAPID keys and browser permission.


# Data Model

The server uses SQLAlchemy models in `server/models.py` and stores data in SQLite at `server/parkwatch.db`.

## Device

Table: `devices`

Represents one Raspberry Pi parking monitor.

Fields:

- `id`: primary key.
- `mac_address`: unique device identifier, indexed.
- `name`: admin-facing name.
- `assigned_plate`: expected license plate for this spot.
- `spot_label`: parking spot label.
- `last_seen`: last heartbeat timestamp.
- `last_wifi`: last reported Wi-Fi quality.
- `last_temp`: last reported CPU temperature.
- `capture_requested`: whether admin requested capture on next heartbeat.
- `current_status`: `empty`, `correct`, or `illegal`.
- `created_at`: creation timestamp.

Relationships:

- `fines`: one device has many fines.

Computed properties:

- `is_online`: true when `last_seen` is within `OFFLINE_THRESHOLD_SECONDS`.

## Fine

Table: `fines`

Represents a detected parking mismatch.

Fields:

- `id`: primary key.
- `device_id`: foreign key to `devices.id`.
- `detected_plate`: plate read by the client.
- `expected_plate`: plate assigned to the parking spot.
- `image_filename`: uploaded evidence image filename.
- `first_seen`: when this mismatch was first seen by the client.
- `last_seen`: when this fine was reported.
- `duration_minutes`: mismatch duration calculated by the client.
- `confidence_score`: OCR confidence score calculated by the client.
- `resolved`: whether the fine has been resolved.
- `photo_requested`: whether the driver requested evidence by email.
- `photo_sent_at`: when evidence email was sent or marked handled.
- `appeal_status`: appeal state.
- `appeal_reason`: reason for human appeal.
- `last_notified`: last push notification timestamp.
- `created_at`: creation timestamp.

Appeal statuses used by the app:

- `none`
- `pending_ai`
- `pending_human`
- `approved`
- `rejected_by_ai`
- `rejected_human`

## User

Table: `users`

Represents either a driver account or admin account.

Fields:

- `id`: primary key.
- `email`: unique login email, indexed.
- `password_hash`: bcrypt password hash.
- `license_plate`: driver plate. Admin users may have an empty value.
- `name`: display name.
- `role`: `driver` or `admin`.
- `verification_status`: `pending`, `approved`, or `rejected`.
- `verification_document`: uploaded proof filename.
- `verification_notes`: admin or system notes.
- `created_at`: creation timestamp.

Computed properties:

- `is_admin`: true when `role == "admin"`.
- `is_verified_driver`: true for approved driver users.

## FineMessage

Table: `fine_messages`

Stores appeal and chat history for a fine.

Fields:

- `id`: primary key.
- `fine_id`: foreign key to `fines.id`.
- `sender`: display sender, such as driver name, `Admin`, `AI Assessor`, or `System`.
- `content`: message body.
- `attachment_filename`: optional upload filename.
- `timestamp`: creation timestamp.

Relationships:

- `fine`: each message belongs to one fine.

## PushSubscription

Table: `push_subscriptions`

Stores browser push subscription objects for users.

Fields:

- `id`: primary key.
- `user_id`: foreign key to `users.id`.
- `subscription_info`: JSON string of the browser subscription object.
- `created_at`: creation timestamp.

Relationships:

- `user`: each subscription belongs to one user.

## Schema Management

The app calls `db.create_all()` during startup.

It also checks the `users` table and adds these columns if missing:

- `role`
- `verification_status`
- `verification_document`
- `verification_notes`

This is a lightweight migration mechanism. For production, use a migration tool such as Flask-Migrate/Alembic.


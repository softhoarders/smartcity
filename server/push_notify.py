"""Web push delivery for owner and driver alerts."""

from __future__ import annotations

import json
import os

from pywebpush import WebPushException, webpush

from models import PushSubscription, SpotBooking, db

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_CLAIMS = {"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@spotflow.com")}


def send_web_push(user, title: str, body: str, *, url: str | None = None) -> None:
    if not VAPID_PRIVATE_KEY or not user:
        return

    payload = {"title": title, "body": body}
    if url:
        payload["url"] = url
    message = json.dumps(payload)

    for sub in PushSubscription.query.filter_by(user_id=user.id).all():
        try:
            sub_info = json.loads(sub.subscription_info)
            webpush(
                subscription_info=sub_info,
                data=message,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException as ex:
            if ex.response and ex.response.status_code in (404, 410):
                db.session.delete(sub)
        except Exception as exc:
            print(f"Error sending push: {exc}")

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def notify_owner_booking_request(booking: SpotBooking) -> None:
    """Desktop push when a renter requests manual approval."""
    if booking.status != "pending_approval":
        return
    listing = booking.listing
    if not listing or listing.approval_mode != "manual":
        return
    owner = listing.owner
    if not owner:
        return

    device = listing.device
    spot = device.spot_label if device else "your spot"
    plate = booking.renter_plate or "A driver"
    kind = "instant" if booking.booking_type == "instant" else "scheduled"
    send_web_push(
        owner,
        "New parking request",
        f"{plate} requested {kind} parking at {spot}. Tap to review.",
        url="/portal/my-spots",
    )

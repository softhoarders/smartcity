"""Fire-and-forget webhooks to n8n when Spotflow events occur."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests

import config

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_url() -> str:
    return (config.N8N_WEBHOOK_BASE_URL or "").rstrip("/")


def _webhook_url(event_type: str) -> str | None:
    if not config.N8N_ENABLED:
        return None
    specific = (config.N8N_WEBHOOK_URLS or {}).get(event_type)
    if specific:
        return specific
    base = _base_url()
    if not base:
        return None
    # Single workflow: POST /webhook/spotflow with event_type in body
    if base.endswith("/spotflow"):
        return base
    return urljoin(base + "/", "spotflow")


def _sign(body: bytes) -> str | None:
    secret = config.N8N_WEBHOOK_SECRET
    if not secret:
        return None
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def emit(event_type: str, payload: dict[str, Any], *, sync: bool = False) -> bool:
    """Send event to n8n. Returns True if dispatched (not necessarily delivered)."""
    url = _webhook_url(event_type)
    if not url:
        return False

    envelope = {
        "event_type": event_type,
        "timestamp": _utcnow_iso(),
        "source": "spotflow",
        "payload": payload,
    }
    body = json.dumps(envelope, default=str).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "Spotflow/1.0"}
    signature = _sign(body)
    if signature:
        headers["X-Spotflow-Signature"] = signature
    api_key = config.N8N_WEBHOOK_API_KEY
    if api_key:
        headers["X-Spotflow-Key"] = api_key

    def _post():
        try:
            resp = requests.post(url, data=body, headers=headers, timeout=12)
            if resp.status_code >= 400:
                logger.warning("n8n webhook %s → %s %s", event_type, resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("n8n webhook %s failed: %s", event_type, exc)

    if sync:
        _post()
        return True
    threading.Thread(target=_post, daemon=True).start()
    return True


def _photo_url(image_filename: str | None) -> str | None:
    if not image_filename:
        return None
    base = (config.PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        return f"/uploads/{image_filename}"
    return f"{base}/uploads/{image_filename}"


def fine_payload(fine, device=None) -> dict[str, Any]:
    device = device or fine.device
    return {
        "fine_id": fine.id,
        "device_id": fine.device_id,
        "bay_id": device.spot_label if device else None,
        "device_name": device.name if device else None,
        "assigned_plate": fine.expected_plate,
        "detected_plate": fine.detected_plate,
        "expected_plate": fine.expected_plate,
        "resolved": fine.resolved,
        "appeal_status": fine.appeal_status,
        "duration_minutes": fine.duration_minutes,
        "confidence_score": fine.confidence_score,
        "photo_url": _photo_url(fine.image_filename),
        "first_seen": fine.first_seen.isoformat() if fine.first_seen else None,
        "created_at": fine.created_at.isoformat() if fine.created_at else None,
    }


def booking_payload(booking) -> dict[str, Any]:
    listing = booking.listing
    device = listing.device if listing else None
    return {
        "booking_id": booking.id,
        "status": booking.status,
        "booking_type": booking.booking_type,
        "renter_id": booking.renter_id,
        "renter_email": booking.renter.email if booking.renter else None,
        "renter_plate": booking.renter_plate,
        "owner_id": listing.owner_id if listing else None,
        "owner_email": listing.owner.email if listing and listing.owner else None,
        "listing_id": booking.listing_id,
        "spot_label": device.spot_label if device else None,
        "device_id": device.id if device else None,
        "approval_mode": listing.approval_mode if listing else None,
        "total_spots": booking.total_spots,
        "starts_at": booking.starts_at.isoformat() if booking.starts_at else None,
        "ends_at": booking.ends_at.isoformat() if booking.ends_at else None,
    }


def on_violation_created(fine, device=None):
    emit("violation.created", fine_payload(fine, device))


def on_violation_resolved(fine):
    emit("violation.resolved", fine_payload(fine))


def on_violation_appeal(fine, action: str):
    payload = fine_payload(fine)
    payload["appeal_action"] = action
    emit("violation.appeal", payload)


def on_booking_event(booking, event_suffix: str):
    """event_suffix e.g. requested, approved, active, completed, rejected."""
    emit(f"booking.{event_suffix}", booking_payload(booking))


def on_plate_verification(user, plate: str, status: str, notes: str | None = None):
    emit(
        "plate.verification",
        {
            "user_id": user.id,
            "user_email": user.email,
            "user_name": user.name,
            "plate": plate,
            "status": status,
            "notes": notes,
        },
    )


def on_wallet_event(user, kind: str, amount: int, description: str):
    emit(
        f"wallet.{kind}",
        {
            "user_id": user.id,
            "user_email": user.email,
            "amount": amount,
            "description": description,
            "balance": int(user.spots_balance or 0),
        },
    )

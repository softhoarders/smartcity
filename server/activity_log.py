"""Automatic activity logging for demand analytics and auditing."""

from __future__ import annotations

import json
from typing import Any

from flask import has_request_context, request
from flask_login import current_user

from models import db, SpotActivityLog


def log_activity(
    event_type: str,
    *,
    user_id: int | None = None,
    listing_id: int | None = None,
    device_id: int | None = None,
    booking_id: int | None = None,
    endpoint: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> SpotActivityLog | None:
    if user_id is None and has_request_context():
        try:
            if current_user.is_authenticated and getattr(current_user, "id", None) and current_user.id > 0:
                user_id = current_user.id
        except Exception:
            pass

    if endpoint is None and has_request_context():
        endpoint = request.endpoint

    entry = SpotActivityLog(
        event_type=event_type,
        user_id=user_id,
        listing_id=listing_id,
        device_id=device_id,
        booking_id=booking_id,
        endpoint=endpoint,
        metadata_json=json.dumps(metadata or {}, default=str)[:4000],
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def log_page_view(page: str, **metadata: Any):
    return log_activity(f"page.view.{page}", metadata=metadata, commit=True)


def count_events(
    event_types: list[str],
    *,
    listing_id: int | None = None,
    device_id: int | None = None,
    since,
) -> int:
    q = SpotActivityLog.query.filter(
        SpotActivityLog.event_type.in_(event_types),
        SpotActivityLog.created_at >= since,
    )
    if listing_id is not None:
        q = q.filter(SpotActivityLog.listing_id == listing_id)
    if device_id is not None:
        q = q.filter(SpotActivityLog.device_id == device_id)
    return q.count()


# Endpoints that auto-log a GET page view
AUTO_LOG_GET_ENDPOINTS = {
    "find_parking": "find_parking",
    "my_spots": "my_spots",
    "wallet": "wallet",
    "wallet_topup": "wallet_topup",
    "portal": "portal",
    "account_settings": "account_settings",
}

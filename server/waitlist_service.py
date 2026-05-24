"""Waitlist creation and auto-book fulfillment when bays free up."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
import spot_prices
import spots_service
from models import Device, SpotBooking, SpotListing, SpotWaitlist, User, db

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def active_waitlists_for_user(user_id: int) -> list[SpotWaitlist]:
    return (
        SpotWaitlist.query.filter_by(user_id=user_id, status="active")
        .order_by(SpotWaitlist.created_at.asc())
        .all()
    )


def create_waitlist(
    user: User,
    listing: SpotListing,
    renter_plate: str,
    window_start: datetime,
    window_end: datetime,
    *,
    max_price_hundredths: int | None = None,
    auto_book: bool | None = None,
) -> SpotWaitlist:
    if auto_book is None:
        auto_book = config.WAITLIST_DEFAULT_AUTO_BOOK

    active_count = SpotWaitlist.query.filter_by(user_id=user.id, status="active").count()
    if active_count >= config.WAITLIST_MAX_ACTIVE_PER_USER:
        raise ValueError(
            f"You can only watch {config.WAITLIST_MAX_ACTIVE_PER_USER} spots at a time."
        )

    starts = _aware(window_start)
    ends = _aware(window_end)
    if not starts or not ends or ends <= starts:
        raise ValueError("Invalid parking window.")

    inst = spot_prices.effective_instant_hundredths(listing)
    if max_price_hundredths is not None and inst > max_price_hundredths:
        raise ValueError("Spot price exceeds your maximum.")

    row = SpotWaitlist(
        user_id=user.id,
        listing_id=listing.id,
        renter_plate=renter_plate,
        window_start=starts,
        window_end=ends,
        max_price_hundredths=max_price_hundredths,
        auto_book=bool(auto_book),
        status="active",
        expires_at=ends + timedelta(hours=1),
    )
    db.session.add(row)
    db.session.commit()
    return row


def cancel_waitlist(user: User, waitlist_id: int) -> bool:
    row = SpotWaitlist.query.filter_by(id=waitlist_id, user_id=user.id, status="active").first()
    if not row:
        return False
    row.status = "cancelled"
    db.session.commit()
    return True


def _estimate_booking_cost(listing: SpotListing, starts: datetime, ends: datetime) -> int:
    hours = max(1, int((ends - starts).total_seconds() // 3600) or 1)
    total, _, _ = spots_service.calculate_scheduled_total(listing, starts, ends)
    return total


def _try_fulfill_one(waitlist: SpotWaitlist, device: Device) -> bool:
    if waitlist.status != "active":
        return False

    now = _utcnow()
    if waitlist.expires_at and _aware(waitlist.expires_at) and _aware(waitlist.expires_at) < now:
        waitlist.status = "expired"
        db.session.commit()
        return False

    window_start = _aware(waitlist.window_start)
    window_end = _aware(waitlist.window_end)
    if not window_start or not window_end:
        return False

    grace = timedelta(minutes=config.WAITLIST_GRACE_MINUTES)
    if window_start > now + grace:
        return False

    listing = waitlist.listing
    if not listing or not listing.is_active:
        waitlist.status = "failed"
        waitlist.failure_reason = "Listing is no longer active."
        db.session.commit()
        _emit_waitlist_event(waitlist, "waitlist.failed")
        return False

    status = (device.current_status or "").lower()
    active = spots_service.active_booking_for_device(device.id, now)
    if status != "empty" or active is not None:
        return False

    user = waitlist.user
    if not waitlist.auto_book:
        waitlist.status = "fulfilled"
        waitlist.failure_reason = None
        db.session.commit()
        _emit_waitlist_event(waitlist, "waitlist.fulfilled")
        return True

    cost = _estimate_booking_cost(listing, window_start, window_end)
    if waitlist.max_price_hundredths is not None:
        per_hour = spot_prices.effective_instant_hundredths(listing)
        if per_hour > waitlist.max_price_hundredths:
            waitlist.status = "failed"
            waitlist.failure_reason = "Price exceeds your maximum."
            db.session.commit()
            _emit_waitlist_event(waitlist, "waitlist.failed")
            return False

    balance = spots_service.user_balance(user)
    if balance < cost:
        waitlist.status = "failed"
        waitlist.failure_reason = "Insufficient Credits for auto-book."
        db.session.commit()
        _emit_waitlist_event(waitlist, "waitlist.failed")
        return False

    try:
        if window_start <= now + timedelta(minutes=5):
            hours = max(1, int((window_end - max(window_start, now)).total_seconds() // 3600) or 1)
            booking = spots_service.create_instant_booking(
                listing, user, waitlist.renter_plate, hours
            )
        else:
            booking = spots_service.create_scheduled_booking(
                listing, user, waitlist.renter_plate, window_start, window_end
            )
        waitlist.status = "fulfilled"
        waitlist.fulfilled_booking_id = booking.id
        waitlist.failure_reason = None
        db.session.commit()
        _emit_waitlist_event(waitlist, "waitlist.fulfilled", booking=booking)
        return True
    except ValueError as exc:
        waitlist.status = "failed"
        waitlist.failure_reason = str(exc)[:255]
        db.session.commit()
        _emit_waitlist_event(waitlist, "waitlist.failed")
        return False


def _emit_waitlist_event(waitlist: SpotWaitlist, event_type: str, booking: SpotBooking | None = None):
    try:
        import n8n_events

        payload = {
            "waitlist_id": waitlist.id,
            "listing_id": waitlist.listing_id,
            "user_id": waitlist.user_id,
            "status": waitlist.status,
            "auto_book": waitlist.auto_book,
            "failure_reason": waitlist.failure_reason,
        }
        if booking:
            payload["booking_id"] = booking.id
        n8n_events.emit(event_type, payload)
    except Exception as exc:
        logger.debug("n8n waitlist event skipped: %s", exc)


def process_waitlists_for_device(device_id: int) -> int:
    """Try to fulfill active waitlists for all listings on this device."""
    listings = SpotListing.query.filter_by(device_id=device_id, is_active=True).all()
    if not listings:
        return 0
    device = Device.query.get(device_id)
    if not device:
        return 0

    fulfilled = 0
    listing_ids = [lst.id for lst in listings]
    waitlists = (
        SpotWaitlist.query.filter(
            SpotWaitlist.listing_id.in_(listing_ids),
            SpotWaitlist.status == "active",
        )
        .order_by(SpotWaitlist.created_at.asc())
        .all()
    )
    for wl in waitlists:
        if _try_fulfill_one(wl, device):
            fulfilled += 1
    return fulfilled


def process_due_waitlists() -> int:
    """Scan devices with active waitlists and attempt fulfillment."""
    listing_ids = [
        row[0]
        for row in db.session.query(SpotWaitlist.listing_id)
        .filter_by(status="active")
        .distinct()
        .all()
    ]
    if not listing_ids:
        return 0
    device_ids = {
        row[0]
        for row in db.session.query(SpotListing.device_id)
        .filter(SpotListing.id.in_(listing_ids))
        .distinct()
        .all()
    }
    total = 0
    for device_id in device_ids:
        total += process_waitlists_for_device(device_id)
    return total


def on_booking_completed(device_id: int) -> None:
    process_waitlists_for_device(device_id)

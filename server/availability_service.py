"""Rule-based parking availability predictions for Find parking."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

import config
from models import Device, SpotBooking, SpotListing
from spots_service import active_booking_for_device

DEFAULT_TURNOVER_HOURS = 2.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _romania_holiday(dt: datetime) -> bool:
    try:
        import holidays

        ro = holidays.Romania(years=dt.year)
        return dt.date() in ro
    except Exception:
        return dt.weekday() >= 5


def _median_booking_hours(listing_id: int, days: int | None = None) -> float:
    days = days or config.AVAILABILITY_HISTORY_DAYS
    since = _utcnow() - timedelta(days=days)
    rows = (
        SpotBooking.query.filter(
            SpotBooking.listing_id == listing_id,
            SpotBooking.created_at >= since,
            SpotBooking.status.in_(("completed", "active", "approved")),
        )
        .all()
    )
    durations = []
    for b in rows:
        starts = _aware(b.starts_at)
        ends = _aware(b.ends_at)
        if starts and ends and ends > starts:
            durations.append((ends - starts).total_seconds() / 3600.0)
    if not durations:
        return DEFAULT_TURNOVER_HOURS
    return max(0.5, statistics.median(durations))


def _hour_demand_factor(listing_id: int, target: datetime) -> float:
    """Lower confidence when this listing is often booked at target hour."""
    since = _utcnow() - timedelta(days=config.AVAILABILITY_HISTORY_DAYS)
    rows = SpotBooking.query.filter(
        SpotBooking.listing_id == listing_id,
        SpotBooking.created_at >= since,
        SpotBooking.status.notin_(("rejected", "cancelled")),
    ).all()
    if not rows:
        return 1.0
    bucket = target.weekday() * 24 + target.hour
    matches = 0
    for b in rows:
        starts = _aware(b.starts_at)
        if not starts:
            continue
        if starts.weekday() * 24 + starts.hour == bucket:
            matches += 1
    ratio = matches / max(1, len(rows))
    return max(0.55, 1.0 - ratio * 0.45)


def _next_blocking_booking(device_id: int, after: datetime) -> SpotBooking | None:
    return (
        SpotBooking.query.join(SpotListing)
        .filter(
            SpotListing.device_id == device_id,
            SpotBooking.status.in_(("pending_approval", "approved", "active")),
            SpotBooking.ends_at > after,
        )
        .order_by(SpotBooking.starts_at.asc())
        .first()
    )


def _format_local_time(dt: datetime) -> str:
    return dt.astimezone().strftime("%H:%M")


def predict_for_listing(
    listing: SpotListing,
    device: Device,
    *,
    target_at: datetime | None = None,
) -> dict[str, Any]:
    now = _utcnow()
    target = _aware(target_at) or (now + timedelta(minutes=30))
    status = (device.current_status or "unknown").lower()

    active = active_booking_for_device(device.id, now)
    free_at: datetime | None = None
    available_now = status == "empty" and active is None

    if active:
        free_at = _aware(active.ends_at)
        available_now = False
    elif status in ("occupied", "correct", "violation", "illegal"):
        turnover_h = _median_booking_hours(listing.id)
        free_at = now + timedelta(hours=turnover_h)
        available_now = False
    elif status == "empty":
        free_at = now
        available_now = True

    future = _next_blocking_booking(device.id, now)
    if future and free_at:
        f_start = _aware(future.starts_at)
        f_end = _aware(future.ends_at)
        if f_start and f_end and f_start <= target < f_end:
            free_at = max(free_at, f_end) if free_at else f_end
            available_now = False
        elif f_start and target >= f_start and free_at < f_start:
            pass

    if free_at and target < free_at:
        delta_h = (free_at - target).total_seconds() / 3600.0
        base_conf = max(25, int(95 - delta_h * 18))
    elif available_now and target <= now + timedelta(minutes=15):
        base_conf = 96
    elif available_now:
        base_conf = 88
    else:
        base_conf = 72

    demand_factor = _hour_demand_factor(listing.id, target)
    if _romania_holiday(target):
        demand_factor *= 0.92
    confidence_pct = int(max(15, min(99, base_conf * demand_factor)))

    if available_now and target <= now + timedelta(minutes=20):
        label = "Available now"
        reason = "This spot is open right now."
    elif free_at and target >= free_at:
        label = f"Likely free by {_format_local_time(free_at)}"
        reason = "Should be free before you arrive."
    elif free_at:
        label = f"May free ~{_format_local_time(free_at)}"
        reason = "Based on recent use of this spot."
    else:
        label = "Availability uncertain"
        reason = "Availability may change."

    return {
        "available_now": available_now,
        "free_at": free_at.isoformat() if free_at else None,
        "confidence_pct": confidence_pct,
        "prediction_label": label,
        "prediction_reason": reason,
        "availability_score": confidence_pct / 100.0,
    }


def predict_for_demo_device(
    device,
    listing_id: int = 0,
    *,
    target_at: datetime | None = None,
    route_kind: str | None = None,
) -> dict[str, Any]:
    """Synthetic predictions for demo listings (mix of open now and predicted free)."""
    now = _utcnow()
    target = _aware(target_at) or (now + timedelta(minutes=30))
    status = (getattr(device, "current_status", None) or "empty").lower()
    lid = listing_id or getattr(device, "id", 0)
    rk = route_kind or getattr(device, "_demo_route_kind", None)

    # Direct bays: more often "available now"; flow bays: mix of walk-route value props
    if rk == "flow":
        if lid % 4 in (0, 1) or status == "empty":
            return {
                "available_now": True,
                "free_at": now.isoformat(),
                "confidence_pct": 91,
                "prediction_label": "Available now",
                "prediction_reason": "Open nearby — walk to your destination.",
                "availability_score": 0.91,
            }
        free_at = now + timedelta(minutes=12 + (lid % 5) * 8)
        conf = 78 + (lid % 15)
        return {
            "available_now": False,
            "free_at": free_at.isoformat(),
            "confidence_pct": conf,
            "prediction_label": f"Likely free by {_format_local_time(free_at)}",
            "prediction_reason": f"~{conf}% chance free before you arrive (flow route).",
            "availability_score": conf / 100.0,
        }

    if status == "empty" or lid % 3 != 2:
        return {
            "available_now": True,
            "free_at": now.isoformat(),
            "confidence_pct": 94,
            "prediction_label": "Available now",
            "prediction_reason": "Open at your destination.",
            "availability_score": 0.94,
        }

    free_at = now + timedelta(hours=1 + (lid % 3))
    conf = 70 + (lid % 20)
    return {
        "available_now": False,
        "free_at": free_at.isoformat(),
        "confidence_pct": conf,
        "prediction_label": f"May free ~{_format_local_time(free_at)}",
        "prediction_reason": "Estimate from recent turnover at this bay.",
        "availability_score": conf / 100.0,
    }


def enrich_listing_items(
    items: list[dict[str, Any]],
    *,
    target_at: datetime | None = None,
    is_demo: bool = False,
) -> list[dict[str, Any]]:
    for item in items:
        listing = item["listing"]
        device = item["device"]
        if is_demo:
            pred = predict_for_demo_device(
                device,
                getattr(listing, "id", 0),
                target_at=target_at,
                route_kind=item.get("route_kind"),
            )
        else:
            pred = predict_for_listing(listing, device, target_at=target_at)
        item.update(pred)
    return items

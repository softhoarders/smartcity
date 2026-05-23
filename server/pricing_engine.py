"""Smart pricing: demand metrics from activity log, rules, optional Gemini."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

import config
from activity_log import count_events
from geo_context import get_geo_context, location_tier
from models import db, Device, SpotBooking, SpotListing
from spot_prices import format_tenths, legacy_instant_tenths, legacy_schedule_tenths

logger = logging.getLogger(__name__)

DEMAND_VIEW_EVENTS = [
    "listing.view",
    "listing.card_view",
    "booking.instant_attempt",
    "booking.schedule_attempt",
    "page.view.find_parking",
]

DEMAND_BOOKING_EVENTS = [
    "booking.instant_created",
    "booking.schedule_created",
    "booking.approved",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _romania_holiday(dt: datetime) -> bool:
    try:
        import holidays

        ro = holidays.Romania(years=dt.year)
        return dt.date() in ro
    except Exception:
        return dt.weekday() >= 5


def collect_demand_signals(listing: SpotListing, device: Device) -> dict[str, Any]:
    now = _utcnow()
    since_7d = now - timedelta(days=7)
    since_24h = now - timedelta(hours=24)

    views_7d = count_events(
        DEMAND_VIEW_EVENTS,
        listing_id=listing.id,
        device_id=device.id,
        since=since_7d,
    )
    views_24h = count_events(
        DEMAND_VIEW_EVENTS,
        listing_id=listing.id,
        device_id=device.id,
        since=since_24h,
    )
    booking_attempts_7d = count_events(
        ["booking.instant_attempt", "booking.schedule_attempt"],
        listing_id=listing.id,
        since=since_7d,
    )
    bookings_7d = SpotBooking.query.filter(
        SpotBooking.listing_id == listing.id,
        SpotBooking.created_at >= since_7d,
        SpotBooking.status.notin_(("rejected", "cancelled")),
    ).count()
    bookings_30d = SpotBooking.query.filter(
        SpotBooking.listing_id == listing.id,
        SpotBooking.created_at >= now - timedelta(days=30),
        SpotBooking.status.notin_(("rejected", "cancelled")),
    ).count()
    pending = SpotBooking.query.filter_by(
        listing_id=listing.id, status="pending_approval"
    ).count()

    geo = get_geo_context(device)
    tier = geo.get("tier") or location_tier(device)

    occupancy_score = 0.0
    if device.current_status in ("occupied", "correct", "illegal", "violation"):
        occupancy_score = 1.0

    return {
        "views_7d": views_7d,
        "views_24h": views_24h,
        "booking_attempts_7d": booking_attempts_7d,
        "bookings_7d": bookings_7d,
        "bookings_30d": bookings_30d,
        "pending_requests": pending,
        "occupancy_score": occupancy_score,
        "location_tier": tier,
        "area_label": geo.get("area_label"),
        "weather_code": geo.get("weather_code"),
        "distance_km_center": geo.get("distance_km_center"),
        "hour": now.hour,
        "weekday": now.weekday(),
        "is_weekend": now.weekday() >= 5,
        "is_holiday": _romania_holiday(now),
    }


def _time_factor(signals: dict) -> float:
    hour = signals["hour"]
    f = 1.0
    if 8 <= hour <= 10 or 17 <= hour <= 19:
        f += 0.15
    elif 22 <= hour or hour < 6:
        f -= 0.08
    if signals["is_weekend"]:
        f += 0.08
    if signals.get("is_holiday"):
        f += 0.12
    return f


def _location_factor(signals: dict) -> float:
    tier = signals.get("location_tier", "unknown")
    return {
        "central": 1.25,
        "inner": 1.1,
        "outer": 0.95,
        "unknown": 1.0,
    }.get(tier, 1.0)


def _demand_factor(signals: dict) -> float:
    views = signals["views_7d"] + signals["views_24h"] * 0.5
    bookings = signals["bookings_7d"]
    pending = signals["pending_requests"]
    attempts = signals["booking_attempts_7d"]
    f = 1.0
    f += min(0.35, views * 0.02)
    f += min(0.25, bookings * 0.05)
    f += min(0.15, pending * 0.08)
    f += min(0.1, attempts * 0.03)
    f += 0.05 * signals.get("occupancy_score", 0)
    return f


def _weather_factor(signals: dict) -> float:
    code = signals.get("weather_code")
    if code is None:
        return 1.0
    if code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        return 1.05
    if code in (71, 73, 75, 85, 86):
        return 1.08
    return 1.0


def rule_based_price_tenths(listing: SpotListing, signals: dict) -> tuple[int, int, str]:
    base_instant = legacy_instant_tenths(listing)
    base_schedule = legacy_schedule_tenths(listing)

    multiplier = (
        _time_factor(signals)
        * _location_factor(signals)
        * _demand_factor(signals)
        * _weather_factor(signals)
    )

    instant = int(round(base_instant * multiplier))
    schedule = int(round(base_schedule * multiplier))

    min_t = listing.owner_min_tenths or config.PRICING_DEFAULT_MIN_TENTHS
    max_t = listing.owner_max_tenths or config.PRICING_DEFAULT_MAX_TENTHS
    instant = max(min_t, min(max_t, instant))
    schedule = max(min_t, min(max_t, schedule))

    reason = (
        f"Demand: {signals['views_7d']} views (7d), {signals['bookings_7d']} bookings; "
        f"{signals['location_tier']} area; "
        f"×{multiplier:.2f} from time, location, and interest."
    )
    return instant, schedule, reason


def _gemini_adjust(
    listing: SpotListing,
    signals: dict,
    rule_instant: int,
    rule_schedule: int,
    rule_reason: str,
) -> tuple[int, int, str] | None:
    if not config.GEMINI_API_KEY or not config.PRICING_GEMINI_ENABLED:
        return None

    prompt = f"""You adjust hourly parking prices in Spots (Romanian lei, 10 tenths = 1.0 Spot).

RULES:
- Respond with JSON only, no markdown.
- suggested_instant_tenths and suggested_schedule_tenths must be integers (tenths).
- Stay within owner_min_tenths and owner_max_tenths.
- Use demand signals; higher interest can raise price modestly.

owner_min_tenths: {listing.owner_min_tenths or config.PRICING_DEFAULT_MIN_TENTHS}
owner_max_tenths: {listing.owner_max_tenths or config.PRICING_DEFAULT_MAX_TENTHS}
rule_based_instant_tenths: {rule_instant}
rule_based_schedule_tenths: {rule_schedule}
signals: {json.dumps(signals, default=str)}

Return:
{{"suggested_instant_tenths": int, "suggested_schedule_tenths": int, "reason": "one short sentence"}}
"""

    try:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 256},
        }
        resp = requests.post(url, json=body, timeout=25)
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        instant = int(data["suggested_instant_tenths"])
        schedule = int(data["suggested_schedule_tenths"])
        min_t = listing.owner_min_tenths or config.PRICING_DEFAULT_MIN_TENTHS
        max_t = listing.owner_max_tenths or config.PRICING_DEFAULT_MAX_TENTHS
        instant = max(min_t, min(max_t, instant))
        schedule = max(min_t, min(max_t, schedule))
        reason = str(data.get("reason") or rule_reason)[:500]
        return instant, schedule, reason
    except Exception as exc:
        logger.warning("Gemini pricing skipped: %s", exc)
        return None


def refresh_listing_prices(listing: SpotListing, *, commit: bool = True) -> dict[str, Any]:
    device = listing.device
    if not device:
        return {"ok": False, "error": "no device"}

    signals = collect_demand_signals(listing, device)
    rule_instant, rule_schedule, rule_reason = rule_based_price_tenths(listing, signals)

    instant, schedule, reason = rule_instant, rule_schedule, rule_reason
    gemini = _gemini_adjust(listing, signals, rule_instant, rule_schedule, rule_reason)
    if gemini:
        instant, schedule, reason = gemini

    listing.suggested_instant_tenths = instant
    listing.suggested_schedule_tenths = schedule
    listing.pricing_reason = reason
    listing.location_zone = signals.get("location_tier")
    listing.last_priced_at = _utcnow()

    if listing.pricing_mode == "auto":
        listing.dynamic_instant_tenths = instant
        listing.dynamic_schedule_tenths = schedule
        listing.instant_price_tenths = instant
        listing.schedule_price_tenths = schedule
        listing.instant_price_per_hour = (instant + 9) // 10
        listing.schedule_price_per_hour = (schedule + 9) // 10

    if commit:
        db.session.commit()

    return {
        "ok": True,
        "instant": format_tenths(instant),
        "schedule": format_tenths(schedule),
        "reason": reason,
        "signals": signals,
    }


def refresh_all_active_listings():
    updated = 0
    for listing in SpotListing.query.filter_by(is_active=True).all():
        if listing.pricing_mode in ("auto", "suggest"):
            refresh_listing_prices(listing, commit=False)
            updated += 1
    db.session.commit()
    return updated


def accept_suggestion(listing: SpotListing) -> None:
    if not listing.suggested_instant_tenths:
        raise ValueError("No price suggestion available")
    listing.instant_price_tenths = listing.suggested_instant_tenths
    listing.schedule_price_tenths = listing.suggested_schedule_tenths or listing.instant_price_tenths
    listing.instant_price_per_hour = (listing.instant_price_tenths + 9) // 10
    listing.schedule_price_per_hour = (listing.schedule_price_tenths + 9) // 10
    listing.dynamic_instant_tenths = listing.suggested_instant_tenths
    listing.dynamic_schedule_tenths = listing.suggested_schedule_tenths
    db.session.commit()

"""Find parking search, filters, and recommendation scoring."""

from __future__ import annotations

import json
import math
from typing import Any

import config
import spot_prices
from geo_context import haversine_km
from models import SpotActivityLog, SpotListing


STATUS_SCORE = {
    "empty": 1.0,
    "correct": 0.85,
    "occupied": 0.55,
    "violation": 0.35,
    "illegal": 0.2,
}


def listing_item_dict(listing, device) -> dict[str, Any]:
    inst = spot_prices.effective_instant_hundredths(listing)
    sched = spot_prices.effective_schedule_hundredths(listing)
    dep = spot_prices.effective_deposit_hundredths(listing)
    return {
        "listing": listing,
        "device": device,
        "instant_display": spot_prices.format_hundredths(inst),
        "schedule_display": spot_prices.format_hundredths(sched),
        "deposit_display": spot_prices.format_hundredths(dep),
        "instant_hundredths": inst,
        "schedule_hundredths": sched,
        "deposit_hundredths": dep,
        "approval_mode": getattr(listing, "approval_mode", "auto"),
        "pricing_mode": getattr(listing, "pricing_mode", "manual"),
    }


def demand_score(listing_id: int, device_id: int) -> float:
    try:
        count = (
            SpotActivityLog.query.filter(
                SpotActivityLog.listing_id == listing_id,
                SpotActivityLog.event_type.in_(
                    (
                        "booking.instant_created",
                        "booking.schedule_created",
                        "listing.card_view",
                    )
                ),
            )
            .count()
        )
        device_count = (
            SpotActivityLog.query.filter_by(device_id=device_id)
            .filter(SpotActivityLog.event_type.like("booking.%"))
            .count()
        )
        return min(1.0, (count + device_count) / 40.0)
    except Exception:
        return 0.0


def placeholder_rating(listing_id: int) -> float:
    return 3.6 + (listing_id % 7) * 0.1


def score_listing(
    item: dict[str, Any],
    center_lat: float,
    center_lng: float,
    max_price_hundredths: int | None = None,
) -> dict[str, Any]:
    device = item["device"]
    lat = getattr(device, "latitude", None)
    lng = getattr(device, "longitude", None)
    distance_km = 999.0
    if lat is not None and lng is not None:
        distance_km = haversine_km(center_lat, center_lng, lat, lng)

    price = item["instant_hundredths"]
    if max_price_hundredths and price > max_price_hundredths:
        item["_filtered_out"] = True

    status = getattr(device, "current_status", "unknown") or "unknown"
    status_s = STATUS_SCORE.get(status, 0.4)
    demand = demand_score(getattr(item["listing"], "id", 0), getattr(device, "id", 0))
    rating = placeholder_rating(getattr(item["listing"], "id", 0))

    dist_score = max(0.0, 1.0 - distance_km / 15.0)
    price_score = max(0.0, 1.0 - price / 3000.0)
    relevance = (
        dist_score * 0.38
        + price_score * 0.22
        + status_s * 0.22
        + demand * 0.1
        + (rating / 5.0) * 0.08
    )

    item["distance_km"] = round(distance_km, 2)
    item["score"] = round(relevance, 4)
    item["rating"] = round(rating, 1)
    item["status"] = status
    return item


def filter_and_sort_listings(
    items: list[dict[str, Any]],
    center_lat: float,
    center_lng: float,
    *,
    min_price: float | None = None,
    max_price: float | None = None,
    max_distance_km: float | None = None,
    booking_mode: str | None = None,
    status_filter: str | None = None,
    sort: str = "relevance",
) -> list[dict[str, Any]]:
    min_h = int(min_price * 100) if min_price is not None else None
    max_h = int(max_price * 100) if max_price is not None else None

    scored = []
    for raw in items:
        item = score_listing(dict(raw), center_lat, center_lng, max_h)
        if min_h is not None and item["instant_hundredths"] < min_h:
            continue
        if max_h is not None and item["instant_hundredths"] > max_h:
            continue
        if max_distance_km is not None and item["distance_km"] > max_distance_km:
            continue
        if status_filter and item["status"] != status_filter:
            continue
        if booking_mode == "instant" and item.get("approval_mode") == "manual":
            pass
        if booking_mode == "schedule" and not item.get("schedule_hundredths"):
            continue
        scored.append(item)

    if sort == "price_asc":
        scored.sort(key=lambda x: x["instant_hundredths"])
    elif sort == "price_desc":
        scored.sort(key=lambda x: -x["instant_hundredths"])
    elif sort == "distance":
        scored.sort(key=lambda x: x["distance_km"])
    else:
        scored.sort(key=lambda x: -x["score"])

    return scored


def top_recommendations(items: list[dict[str, Any]], n: int = 3) -> list[dict[str, Any]]:
    return list(items[:n])

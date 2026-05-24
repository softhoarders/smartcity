"""AI parking concierge: parse natural language and match listings."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import config
import find_parking_service
import gemini_client
import spot_prices
import spots_service
from geo_context import CITY_REGIONS, detect_city_from_text, geocode_search, normalize_city_name
from models import SpotBooking, SpotListing, User

logger = logging.getLogger(__name__)

RO_TZ = ZoneInfo("Europe/Bucharest")


@dataclass
class ConciergeIntent:
    location_query: str
    arrive_at: datetime
    duration_hours: int
    max_price_per_hour_credits: int | None
    booking_type: str
    needs_clarification: bool
    clarification_question: str | None
    user_summary: str
    city: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "location_query": self.location_query,
            "city": self.city,
            "arrive_at": self.arrive_at.isoformat(),
            "duration_hours": self.duration_hours,
            "max_price_per_hour_credits": self.max_price_per_hour_credits,
            "booking_type": self.booking_type,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "user_summary": self.user_summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConciergeIntent:
        arrive_raw = data.get("arrive_at")
        if isinstance(arrive_raw, str):
            arrive_at = datetime.fromisoformat(arrive_raw.replace("Z", "+00:00"))
        else:
            arrive_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        if arrive_at.tzinfo is None:
            arrive_at = arrive_at.replace(tzinfo=timezone.utc)
        return cls(
            location_query=str(data.get("location_query") or "Bucharest"),
            city=normalize_city_name(data.get("city")),
            arrive_at=arrive_at,
            duration_hours=max(1, min(72, int(data.get("duration_hours") or 2))),
            max_price_per_hour_credits=(
                int(data["max_price_per_hour_credits"])
                if data.get("max_price_per_hour_credits") not in (None, "")
                else None
            ),
            booking_type=str(data.get("booking_type") or "either"),
            needs_clarification=bool(data.get("needs_clarification")),
            clarification_question=data.get("clarification_question"),
            user_summary=str(data.get("user_summary") or ""),
        )


@dataclass
class ConciergeResult:
    reply_text: str
    intent: ConciergeIntent
    search_center: dict[str, Any] | None
    results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply_text": self.reply_text,
            "intent": self.intent.to_dict(),
            "search_center": self.search_center,
            "results": self.results,
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_arrive_at(raw: str | None, now: datetime) -> datetime:
    if not raw:
        return now + timedelta(minutes=30)
    text = str(raw).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=RO_TZ).astimezone(timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return now + timedelta(minutes=30)


_CITY_LANDMARKS: dict[str, dict[str, str]] = {
    "Bucharest": {
        "universitate": "Piata Universitatii, Bucharest, Romania",
        "university": "Piata Universitatii, Bucharest, Romania",
        "victoriei": "Calea Victoriei, Bucharest, Romania",
        "unirii": "Piata Unirii, Bucharest, Romania",
        "old town": "Bucharest Old Town, Romania",
        "centru vechi": "Bucharest Old Town, Romania",
        "lipscani": "Lipscani, Bucharest Old Town, Romania",
        "herastrau": "Herastrau Park, Bucharest, Romania",
        "otopeni": "Henri Coanda Airport, Bucharest, Romania",
    },
    "Cluj-Napoca": {
        "universitate": "Universitatea Babes-Bolyai, Cluj-Napoca, Romania",
        "university": "Universitatea Babes-Bolyai, Cluj-Napoca, Romania",
        "babes": "Universitatea Babes-Bolyai, Cluj-Napoca, Romania",
        "bolyai": "Universitatea Babes-Bolyai, Cluj-Napoca, Romania",
        "piezisa": "Piezisa, Cluj-Napoca, Romania",
        "memorandumului": "Piata Memorandumului, Cluj-Napoca, Romania",
        "unirii": "Piata Unirii, Cluj-Napoca, Romania",
        "gara": "Cluj-Napoca railway station, Romania",
    },
    "Craiova": {
        "universitate": "University of Craiova, Craiova, Romania",
        "university": "University of Craiova, Craiova, Romania",
        "centru": "Centrul Istoric, Craiova, Romania",
        "unirii": "Piata Mihai Viteazu, Craiova, Romania",
    },
}


def _resolve_location_query(message: str, city: str) -> str:
    msg = (message or "").lower()
    landmarks = _CITY_LANDMARKS.get(city, {})
    for key in sorted(landmarks.keys(), key=len, reverse=True):
        if key in msg:
            return landmarks[key]
    return f"{city}, Romania"


def parse_intent_demo(message: str) -> ConciergeIntent:
    """Keyword stub when Gemini is unavailable or demo mode."""
    msg = (message or "").lower()
    now = _utcnow()
    city = detect_city_from_text(message) or "Bucharest"
    location_query = _resolve_location_query(message, city)

    hours = 2
    m = re.search(r"(\d+)\s*h", msg)
    if m:
        hours = max(1, min(72, int(m.group(1))))

    max_price = None
    m = re.search(r"(\d+)\s*(credit|lei|ron)", msg)
    if m:
        max_price = int(m.group(1))

    arrive = now + timedelta(hours=2)
    if "tomorrow" in msg:
        arrive = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    if "tonight" in msg or "evening" in msg:
        arrive = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if arrive <= now:
            arrive += timedelta(hours=2)

    return ConciergeIntent(
        location_query=location_query,
        city=city,
        arrive_at=arrive.astimezone(timezone.utc),
        duration_hours=hours,
        max_price_per_hour_credits=max_price,
        booking_type="either",
        needs_clarification=False,
        clarification_question=None,
        user_summary=f"Parking near {location_query.split(',')[0]} for {hours}h",
    )


def parse_intent(
    message: str,
    *,
    user_plates: list[str],
    balance: int,
) -> ConciergeIntent:
    if not config.CONCIERGE_ENABLED or not gemini_client.is_configured():
        return parse_intent_demo(message)

    now = _utcnow().astimezone(RO_TZ).isoformat()
    prompt = f"""You are Spotflow parking concierge for Romania. Parse the driver request into JSON only.

Current local time (Europe/Bucharest): {now}
User balance in Credits: {balance}
User plates: {", ".join(user_plates) or "none"}

Request:
\"\"\"{(message or "")[:800]}\"\"\"

Return JSON:
{{
  "city": "Bucharest" | "Cluj-Napoca" | "Craiova" | null,
  "location_query": "specific place or landmark to geocode, including the city when known (e.g. Universitatea Babes-Bolyai, Cluj-Napoca)",
  "arrive_at": "ISO-8601 datetime with timezone, e.g. 2026-05-24T20:00:00+03:00",
  "duration_hours": integer 1-72,
  "max_price_per_hour_credits": number or null,
  "booking_type": "instant" | "scheduled" | "either",
  "needs_clarification": boolean,
  "clarification_question": string or null,
  "user_summary": "one sentence for the user"
}}
"""
    try:
        data = gemini_client.generate_json(
            [{"text": prompt}],
            model=config.CONCIERGE_MODEL,
            max_output_tokens=600,
        )
        arrive = _parse_arrive_at(data.get("arrive_at"), _utcnow())
        raw_city = normalize_city_name(data.get("city")) or detect_city_from_text(message)
        location_query = str(data.get("location_query") or raw_city or "Bucharest")
        return ConciergeIntent(
            location_query=location_query,
            city=raw_city,
            arrive_at=arrive,
            duration_hours=max(1, min(72, int(data.get("duration_hours") or 2))),
            max_price_per_hour_credits=(
                int(data["max_price_per_hour_credits"])
                if data.get("max_price_per_hour_credits") not in (None, "", "null")
                else None
            ),
            booking_type=str(data.get("booking_type") or "either"),
            needs_clarification=bool(data.get("needs_clarification")),
            clarification_question=data.get("clarification_question"),
            user_summary=str(data.get("user_summary") or "Here are spots that may work."),
        )
    except Exception as exc:
        logger.warning("Concierge Gemini parse failed: %s", exc)
        return parse_intent_demo(message)


def _listing_result_payload(item: dict[str, Any], intent: ConciergeIntent) -> dict[str, Any]:
    listing = item["listing"]
    device = item["device"]
    ends = intent.arrive_at + timedelta(hours=intent.duration_hours)
    hours = max(1, int(intent.duration_hours))
    total_est = 0
    try:
        if intent.booking_type == "instant" or intent.booking_type == "either":
            total_est = spots_service.calculate_instant_total(listing, hours)
        else:
            total_est, _, _ = spots_service.calculate_scheduled_total(
                listing, intent.arrive_at, ends
            )
    except Exception:
        inst_h = item.get("instant_hundredths")
        if inst_h is not None:
            total_est = spot_prices.hundredths_to_billable_spots(int(inst_h) * hours)
        else:
            total_est = 0

    inst = item.get("instant_hundredths")
    if inst is None:
        inst = spot_prices.effective_instant_hundredths(listing)
    return {
        "listing_id": listing.id,
        "spot_label": device.spot_label,
        "name": device.name,
        "lat": getattr(device, "latitude", None),
        "lng": getattr(device, "longitude", None),
        "distance_km": item.get("distance_km"),
        "instant_display": item.get("instant_display"),
        "schedule_display": item.get("schedule_display"),
        "approval_mode": item.get("approval_mode"),
        "score": item.get("score"),
        "prediction_label": item.get("prediction_label"),
        "confidence_pct": item.get("confidence_pct"),
        "available_now": item.get("available_now"),
        "estimated_total_credits": total_est,
        "rate_hundredths": inst,
        "route_kind": item.get("route_kind"),
        "route_label": item.get("route_label"),
        "walk_minutes": item.get("walk_minutes"),
        "min_trust_score": int(getattr(listing, "min_trust_score", 0) or 0),
    }


def search_for_intent(
    intent: ConciergeIntent,
    listings_pool: list[dict[str, Any]],
    *,
    is_demo: bool = False,
) -> ConciergeResult:
    if intent.needs_clarification:
        return ConciergeResult(
            reply_text=intent.clarification_question or "Could you share where and when you need parking?",
            intent=intent,
            search_center=None,
            results=[],
        )

    geocoded = geocode_search(
        intent.location_query,
        limit=3,
        city=intent.city or detect_city_from_text(intent.location_query),
    )
    if geocoded:
        center = geocoded[0]
    else:
        city_name = intent.city or detect_city_from_text(intent.location_query) or "Bucharest"
        region = CITY_REGIONS.get(city_name)
        if region:
            clat, clng = region["center"]
            center = {
                "label": intent.location_query,
                "lat": clat,
                "lng": clng,
            }
        else:
            center = {
                "label": intent.location_query,
                "lat": config.BUCHAREST_CENTER_LAT,
                "lng": config.BUCHAREST_CENTER_LNG,
            }

    import availability_service

    enriched = availability_service.enrich_listing_items(
        [dict(x) for x in listings_pool],
        target_at=intent.arrive_at,
        is_demo=is_demo,
    )

    max_h = None
    if intent.max_price_per_hour_credits is not None:
        max_h = int(intent.max_price_per_hour_credits) * 100

    filtered = find_parking_service.filter_and_sort_listings(
        enriched,
        center["lat"],
        center["lng"],
        max_price=max_h / 100.0 if max_h else None,
        max_distance_km=config.FIND_PARKING_RADIUS_KM,
        sort="relevance",
    )

    import routing_service

    routing_service.enrich_route_plan(
        filtered, center["lat"], center["lng"], destination_label=center.get("label")
    )
    top = routing_service.top_mixed_recommendations(
        filtered,
        direct_n=config.ROUTING_CONCIERGE_DIRECT,
        flow_n=config.ROUTING_CONCIERGE_FLOW,
        total_cap=config.ROUTING_CONCIERGE_TOTAL,
    )
    results = [_listing_result_payload(item, intent) for item in top]

    if results:
        reply = f"{intent.user_summary} I found {len(results)} spot(s) nearby."
    else:
        reply = f"{intent.user_summary} No spots matched — try a larger area or higher max price."

    return ConciergeResult(
        reply_text=reply,
        intent=intent,
        search_center={
            "lat": center["lat"],
            "lng": center["lng"],
            "label": center.get("label", intent.location_query),
        },
        results=results,
    )


def execute_booking(
    listing_id: int,
    intent: ConciergeIntent,
    user: User,
    renter_plate: str,
    *,
    promo_code: str | None = None,
) -> SpotBooking:
    listing = SpotListing.query.filter_by(id=listing_id, is_active=True).first()
    if not listing:
        raise ValueError("Listing not found or inactive.")

    ends = intent.arrive_at + timedelta(hours=intent.duration_hours)
    now = _utcnow()

    if intent.booking_type == "scheduled" or (
        intent.booking_type == "either" and intent.arrive_at > now + timedelta(minutes=20)
    ):
        return spots_service.create_scheduled_booking(
            listing, user, renter_plate, intent.arrive_at, ends, promo_code=promo_code
        )

    hours = max(1, intent.duration_hours)
    return spots_service.create_instant_booking(
        listing, user, renter_plate, hours, promo_code=promo_code
    )

"""Location and weather context (free APIs, cached per device)."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone

import requests

import config
from models import db, Device, SpotGeoCache

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def geocode_search(query: str, limit: int = 5) -> list[dict]:
    """Forward geocode a place name via Nominatim."""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": limit, "countrycodes": "ro"},
            headers={"User-Agent": config.NOMINATIM_USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = []
        for row in resp.json():
            results.append(
                {
                    "label": row.get("display_name", q),
                    "lat": float(row["lat"]),
                    "lng": float(row["lon"]),
                }
            )
        return results
    except Exception as exc:
        logger.debug("Nominatim search failed: %s", exc)
        return []


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def location_tier(device: Device) -> str:
    if device.latitude is None or device.longitude is None:
        return "unknown"
    km = haversine_km(
        device.latitude,
        device.longitude,
        config.BUCHAREST_CENTER_LAT,
        config.BUCHAREST_CENTER_LNG,
    )
    if km < config.PRICING_CENTRAL_KM:
        return "central"
    if km < config.PRICING_INNER_KM:
        return "inner"
    return "outer"


def _cache_row(device_id: int) -> SpotGeoCache | None:
    return SpotGeoCache.query.filter_by(device_id=device_id).first()


def get_geo_context(device: Device, force_refresh: bool = False) -> dict:
    """Nominatim reverse geocode + Open-Meteo weather, cached."""
    if device.latitude is None or device.longitude is None:
        return {"tier": "unknown", "area_label": None, "weather_code": None}

    row = _cache_row(device.id)
    fresh = (
        row
        and row.fetched_at
        and (_utcnow() - row.fetched_at.replace(tzinfo=timezone.utc)).total_seconds()
        < config.GEO_CACHE_HOURS * 3600
    )
    if fresh and not force_refresh:
        try:
            data = json.loads(row.data_json or "{}")
            data.setdefault("tier", location_tier(device))
            return data
        except json.JSONDecodeError:
            pass

    data: dict = {
        "tier": location_tier(device),
        "area_label": None,
        "weather_code": None,
        "distance_km_center": round(
            haversine_km(
                device.latitude,
                device.longitude,
                config.BUCHAREST_CENTER_LAT,
                config.BUCHAREST_CENTER_LNG,
            ),
            2,
        ),
    }

    try:
        nom = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": device.latitude,
                "lon": device.longitude,
                "format": "json",
                "zoom": 16,
            },
            headers={"User-Agent": config.NOMINATIM_USER_AGENT},
            timeout=8,
        )
        nom.raise_for_status()
        addr = nom.json().get("address", {})
        data["area_label"] = (
            addr.get("road")
            or addr.get("suburb")
            or addr.get("neighbourhood")
            or addr.get("city")
            or addr.get("town")
        )
    except Exception as exc:
        logger.debug("Nominatim failed for device %s: %s", device.id, exc)

    try:
        wx = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": device.latitude,
                "longitude": device.longitude,
                "current": "weather_code",
                "timezone": "auto",
            },
            timeout=8,
        )
        wx.raise_for_status()
        data["weather_code"] = wx.json().get("current", {}).get("weather_code")
    except Exception as exc:
        logger.debug("Open-Meteo failed for device %s: %s", device.id, exc)

    payload = json.dumps(data)
    if row:
        row.data_json = payload
        row.fetched_at = _utcnow()
    else:
        db.session.add(
            SpotGeoCache(device_id=device.id, data_json=payload, fetched_at=_utcnow())
        )
    db.session.commit()
    return data

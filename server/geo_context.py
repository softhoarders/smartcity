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


# City centers and viewboxes for biased geocoding (left, top, right, bottom = lon/lat).
CITY_REGIONS: dict[str, dict] = {
    "Bucharest": {
        "center": (44.4268, 26.1025),
        "viewbox": "26.00,44.55,26.30,44.30",
        "max_km": 35,
    },
    "Cluj-Napoca": {
        "center": (46.7712, 23.6236),
        "viewbox": "23.52,46.82,23.72,46.72",
        "max_km": 25,
    },
    "Craiova": {
        "center": (44.3302, 23.7949),
        "viewbox": "23.72,44.38,23.88,44.28",
        "max_km": 20,
    },
}

_CITY_ALIASES: dict[str, str] = {
    "bucharest": "Bucharest",
    "bucuresti": "Bucharest",
    "bucurești": "Bucharest",
    "cluj": "Cluj-Napoca",
    "cluj-napoca": "Cluj-Napoca",
    "cluj napoca": "Cluj-Napoca",
    "craiova": "Craiova",
}


def detect_city_from_text(text: str) -> str | None:
    """Return canonical city name if the message mentions a supported city."""
    msg = (text or "").lower()
    if "cluj" in msg:
        return "Cluj-Napoca"
    if "craiova" in msg:
        return "Craiova"
    if any(tok in msg for tok in ("bucharest", "bucuresti", "bucurești")):
        return "Bucharest"
    return None


def normalize_city_name(city: str | None) -> str | None:
    if not city:
        return None
    key = city.strip().lower()
    return _CITY_ALIASES.get(key, city.strip())


def _rank_by_city(results: list[dict], city: str) -> list[dict]:
    region = CITY_REGIONS.get(city)
    if not region or not results:
        return results
    clat, clng = region["center"]
    max_km = float(region.get("max_km", 40))

    def score(row: dict) -> tuple[float, float]:
        dist = haversine_km(clat, clng, row["lat"], row["lng"])
        importance = float(row.get("importance") or 0)
        return (dist if dist <= max_km else max_km + 100 + dist, -importance)

    ranked = sorted(results, key=score)
    in_city = [r for r in ranked if haversine_km(clat, clng, r["lat"], r["lng"]) <= max_km]
    return in_city or ranked


def geocode_search(query: str, limit: int = 5, *, city: str | None = None) -> list[dict]:
    """Forward geocode a place name via Nominatim, optionally biased to a Romanian city."""
    q = (query or "").strip()
    if len(q) < 2:
        return []

    city_name = normalize_city_name(city) or detect_city_from_text(q)
    search_q = q
    if city_name and city_name.lower() not in q.lower():
        if "romania" not in q.lower() and "românia" not in q.lower():
            search_q = f"{q}, {city_name}, Romania"
        else:
            search_q = f"{q}, {city_name}"

    params: dict[str, str | int] = {
        "q": search_q,
        "format": "json",
        "limit": max(limit, 5),
        "countrycodes": "ro",
        "addressdetails": 1,
    }
    region = CITY_REGIONS.get(city_name) if city_name else None
    if region:
        params["viewbox"] = region["viewbox"]
        params["bounded"] = 1

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
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
                    "importance": row.get("importance"),
                }
            )
        if city_name:
            results = _rank_by_city(results, city_name)
        return results[:limit]
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

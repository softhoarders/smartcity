"""Parking lot navigation helpers — entrance point + in-lot maneuver steps."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any


_ROW_RE = re.compile(r"^([A-Za-z]+)-(\d+)$")
_GENERIC_RE = re.compile(r"(\d+)")


def _spot_seed(spot_label: str, lat: float, lng: float) -> int:
    raw = f"{spot_label}|{lat:.5f}|{lng:.5f}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def parse_spot_label(spot_label: str) -> dict[str, Any]:
    """Parse labels like B-042 into row/number metadata."""
    label = (spot_label or "").strip()
    match = _ROW_RE.match(label)
    if match:
        row = match.group(1).upper()
        number = int(match.group(2))
        return {
            "label": label,
            "row": row,
            "number": number,
            "side": "left" if number % 2 == 0 else "right",
        }
    nums = _GENERIC_RE.findall(label)
    number = int(nums[-1]) if nums else _spot_seed(label, 0.0, 0.0) % 40 + 1
    row = chr(ord("A") + (number % 8))
    return {
        "label": label or "Your spot",
        "row": row,
        "number": number,
        "side": "left" if number % 2 == 0 else "right",
    }


def lot_entrance(lat: float, lng: float, spot_label: str) -> dict[str, float]:
    """
    Synthetic lot entrance ~90–120 m from the bay, on the "street" side.
    Deterministic per spot so the map stays stable across reloads.
    """
    seed = _spot_seed(spot_label, lat, lng)
    bearing_deg = seed % 360
    distance_m = 90 + (seed % 31)
    rad = math.radians(bearing_deg)
    lat_delta = (distance_m * math.cos(rad)) / 111_000.0
    lng_scale = 111_000.0 * max(0.2, math.cos(math.radians(lat)))
    lng_delta = (distance_m * math.sin(rad)) / lng_scale
    return {
        "lat": round(lat + lat_delta, 6),
        "lng": round(lng + lng_delta, 6),
    }


def _cardinal(bearing_deg: float) -> str:
    dirs = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
    idx = int((bearing_deg + 22.5) // 45) % 8
    return dirs[idx]


def in_lot_maneuvers(
    spot_label: str,
    location_name: str,
    lat: float,
    lng: float,
) -> list[dict[str, str]]:
    """Step-by-step instructions once you reach the lot entrance."""
    meta = parse_spot_label(spot_label)
    seed = _spot_seed(spot_label, lat, lng)
    entrance = lot_entrance(lat, lng, spot_label)
    bearing = math.degrees(
        math.atan2(
            lng - entrance["lng"],
            lat - entrance["lat"],
        )
    )
    entry_dir = _cardinal((bearing + 180) % 360)
    row = meta["row"]
    number = meta["number"]
    side = meta["side"]
    aisle_letter = chr(ord(row) - 1) if row > "A" else "A"
    turn = "right" if seed % 2 else "left"
    spaces_from_end = (number % 12) + 2
    place = location_name or "the parking area"

    steps = [
        {
            "phase": "lot",
            "kind": "enter",
            "instruction": f"Enter {place} from the {entry_dir} — look for the main driveway sign.",
        },
        {
            "phase": "lot",
            "kind": "straight",
            "instruction": f"Drive straight past Row {aisle_letter} — stay in the main aisle (speed limit 10 km/h).",
        },
        {
            "phase": "lot",
            "kind": "turn",
            "instruction": f"Turn {turn} into Row {row} — your reserved bay is marked {meta['label']}.",
        },
        {
            "phase": "lot",
            "kind": "spot",
            "instruction": (
                f"Spot {meta['label']} is on your {side}, about {spaces_from_end} spaces from the aisle end. "
                "Pull in forward; your plate is already authorized."
            ),
        },
    ]
    return steps


def build_navigation_plan(
    lat: float,
    lng: float,
    spot_label: str,
    location_name: str = "",
) -> dict[str, Any]:
    """Full plan consumed by the navigate page."""
    entrance = lot_entrance(lat, lng, spot_label)
    meta = parse_spot_label(spot_label)
    return {
        "spot": {
            "label": meta["label"],
            "lat": lat,
            "lng": lng,
            "row": meta["row"],
            "number": meta["number"],
            "location_name": location_name or "",
        },
        "entrance": entrance,
        "lot_steps": in_lot_maneuvers(spot_label, location_name, lat, lng),
    }

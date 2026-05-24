"""Predictive flow routing: at-destination vs park-nearby-and-walk."""

from __future__ import annotations

from typing import Any

import config
from geo_context import haversine_km


def walk_minutes(distance_km: float) -> int:
    speed = config.ROUTING_WALK_SPEED_KMH
    if speed <= 0:
        return max(1, int(round(distance_km * 12)))
    return max(1, int(round((distance_km / speed) * 60)))


def enrich_route_plan(
    items: list[dict[str, Any]],
    center_lat: float,
    center_lng: float,
    *,
    destination_label: str | None = None,
) -> list[dict[str, Any]]:
    """Tag each listing with route_kind direct|flow and walk metadata."""
    dest = (destination_label or "your destination").strip()
    direct_km = config.ROUTING_DIRECT_MAX_KM

    for item in items:
        device = item.get("device")
        lat = getattr(device, "latitude", None) if device else item.get("lat")
        lng = getattr(device, "longitude", None) if device else item.get("lng")
        distance = item.get("distance_km")
        if distance is None and lat is not None and lng is not None:
            distance = haversine_km(center_lat, center_lng, lat, lng)
            item["distance_km"] = round(distance, 2)
        distance = float(distance or 999.0)
        walk = walk_minutes(distance)

        if distance <= direct_km:
            item["route_kind"] = "direct"
            item["route_label"] = "At your destination"
            item["route_hint"] = f"About {walk} min walk to {dest}" if walk <= 5 else f"Right by {dest}"
        else:
            item["route_kind"] = "flow"
            item["route_label"] = f"Park here · walk {walk} min"
            item["route_hint"] = (
                f"Higher chance to find space · {distance:.1f} km from {dest}, ~{walk} min on foot"
            )
        item["walk_minutes"] = walk

    return items


def split_route_sections(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    direct = [i for i in items if i.get("route_kind") == "direct"]
    flow = [i for i in items if i.get("route_kind") == "flow"]
    return {"direct": direct, "flow": flow}


def top_mixed_recommendations(
    items: list[dict[str, Any]],
    *,
    direct_n: int = 2,
    flow_n: int = 2,
    total_cap: int = 4,
) -> list[dict[str, Any]]:
    """Pick top direct and flow picks so demos always show both strategies."""
    sections = split_route_sections(items)
    direct = sorted(sections["direct"], key=lambda x: -x.get("score", 0))[:direct_n]
    flow = sorted(sections["flow"], key=lambda x: -x.get("score", 0))[:flow_n]
    mixed = direct + flow
    if len(mixed) < total_cap:
        seen = {i["listing"].id for i in mixed if i.get("listing")}
        for item in items:
            lid = getattr(item.get("listing"), "id", None)
            if lid in seen:
                continue
            mixed.append(item)
            seen.add(lid)
            if len(mixed) >= total_cap:
                break
    return mixed[:total_cap]


def flow_route_summary(items: list[dict[str, Any]], destination_label: str) -> str | None:
    flow = [i for i in items if i.get("route_kind") == "flow" and i.get("available_now")]
    if not flow:
        return None
    best = min(flow, key=lambda x: (x.get("walk_minutes", 99), x.get("instant_hundredths", 99999)))
    walk = best.get("walk_minutes", "?")
    label = best.get("device")
    spot = getattr(label, "spot_label", "a nearby bay") if label else "a nearby bay"
    return (
        f"Tip: {spot} is open now — park there and walk ~{walk} min to {destination_label}."
    )

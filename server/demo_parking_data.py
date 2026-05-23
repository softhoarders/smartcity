"""Mass demo devices and rental listings for Find parking."""

from __future__ import annotations

import random
from datetime import timedelta
from types import SimpleNamespace

import spot_prices

# Deterministic variety per session seed could change; fixed seed for stable demos.
_rng = random.Random(42)

CITIES = (
    ("Bucharest", 44.4268, 26.1025, 0.045),
    ("Cluj-Napoca", 46.7712, 23.6236, 0.035),
    ("Craiova", 44.3302, 23.7949, 0.032),
)

STATUSES = ("empty", "occupied", "correct", "violation", "illegal")
ZONES = {
    "Bucharest": (
        "Calea Victoriei",
        "Piata Universitatii",
        "Herastrau",
        "Titan",
        "Drumul Taberei",
        "Old Town",
    ),
    "Cluj-Napoca": ("Centru", "Gheorgheni", "Marasti", "Zorilor", "Iris"),
    "Craiova": ("Centru", "Rovine", "Brazda lui Novac", "Făcăi", "Sterea"),
}


def _price_hundredths() -> int:
    return _rng.choice(
        [
            850,
            950,
            1050,
            1125,
            1200,
            1275,
            1350,
            1450,
            1550,
            1650,
            1750,
            1890,
            2100,
            2250,
        ]
    )


def build_demo_devices(now_fn):
    base = now_fn()
    devices = []
    dev_id = 200
    for city, clat, clng, spread in CITIES:
        zones = ZONES[city]
        for i in range(18):
            lat = clat + _rng.uniform(-spread, spread)
            lng = clng + _rng.uniform(-spread, spread)
            zone = zones[i % len(zones)]
            status = STATUSES[i % len(STATUSES)]
            plate = None
            if status in ("occupied", "correct", "violation"):
                plate = f"B-{_rng.randint(100, 999)}-{_rng.choice(['MAB', 'XYZ', 'ABC', 'KLM'])}"
            online = status != "empty" or i % 5 != 0
            d = SimpleNamespace()
            d.id = dev_id
            d.name = f"{city} — {zone}"
            d.spot_label = f"{city[:2].upper()}-{i + 1:02d}"
            d.assigned_plate = plate
            d.current_status = status
            d.is_online = online
            d.mac_address = f"DE:MO:{dev_id:04X}:00:01"
            d.last_seen = base - timedelta(seconds=30 if online else 4000)
            d.last_wifi = _rng.randint(55, 92) if online else None
            d.last_temp = round(_rng.uniform(45.0, 56.0), 1) if online else None
            d.created_at = base - timedelta(days=20 + i)
            d.capture_requested = status == "violation" and i % 3 == 0
            d.latitude = round(lat, 5)
            d.longitude = round(lng, 5)
            d.location_zone = zone
            d.notes = f"Demo bay in {city}"
            d.fines = SimpleNamespace(count=lambda: _rng.randint(0, 2))
            devices.append(d)
            dev_id += 1

    # Legacy showcase devices (portal fines / my spots)
    legacy = [
        (101, "Calea Victoriei — Level 1", "P1-12", "B-123-MAB", "occupied", 44.4383, 26.1034, "Calea Victoriei"),
        (105, "Piata Universitatii — Garage", "P2-04", "B-441-PKR", "correct", 44.4358, 26.1025, "Piata Universitatii"),
        (113, "Calea Victoriei — Rooftop", "P3-02", "B-212-GLS", "occupied", 44.4380, 26.1040, "Calea Victoriei"),
    ]
    for lid, name, spot, plate, status, lat, lng, zone in legacy:
        d = SimpleNamespace()
        d.id = lid
        d.name = name
        d.spot_label = spot
        d.assigned_plate = plate
        d.current_status = status
        d.is_online = True
        d.mac_address = f"AA:BB:CC:DD:EE:{lid:02X}"
        d.last_seen = base - timedelta(seconds=25)
        d.last_wifi = 80
        d.last_temp = 50.0
        d.created_at = base - timedelta(days=30)
        d.capture_requested = False
        d.latitude = lat
        d.longitude = lng
        d.location_zone = zone
        d.notes = "Legacy demo spot"
        d.fines = SimpleNamespace(count=lambda: 1)
        devices.append(d)

    return devices


def build_demo_rental_listings(devices, now_fn):
    items = []
    listing_id = 1
    for d in devices:
        if d.id < 200 and d.id not in (105, 109, 113):
            continue
        inst = _price_hundredths()
        sched = max(800, inst - _rng.choice([50, 100, 150, 200]))
        deposit = _rng.choice([400, 500, 600, 750, 800])
        listing = SimpleNamespace(
            id=listing_id,
            is_active=True,
            approval_mode=_rng.choice(["auto", "auto", "manual"]),
            pricing_mode=_rng.choice(["auto", "manual", "manual"]),
            description=_rng.choice(
                [
                    "Covered spot near metro.",
                    "EV-friendly driveway.",
                    "Quiet residential bay.",
                    "Office park — weekdays.",
                    "Short-term curbside rent.",
                ]
            ),
            owner_min_tenths=500,
            owner_max_tenths=3000,
            instant_price_tenths=inst,
            schedule_price_tenths=sched,
            schedule_deposit_tenths=deposit,
            instant_price_per_hour=(inst + 99) // 100,
            schedule_price_per_hour=(sched + 99) // 100,
            schedule_deposit_spots=(deposit + 99) // 100,
        )
        items.append(
            {
                "listing": listing,
                "device": d,
                "instant_display": spot_prices.format_hundredths(inst),
                "schedule_display": spot_prices.format_hundredths(sched),
                "deposit_display": spot_prices.format_hundredths(deposit),
                "instant_hundredths": inst,
                "schedule_hundredths": sched,
                "deposit_hundredths": deposit,
            }
        )
        listing_id += 1
    return items

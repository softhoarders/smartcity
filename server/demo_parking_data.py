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

CITY_CODES = {
    "Bucharest": "B",
    "Cluj-Napoca": "CL",
    "Craiova": "CR",
}

# Real neighborhood anchors — spots cluster near these coordinates within each city.
CITY_NEIGHBORHOODS = {
    "Bucharest": (
        ("Centru — Lipscani", 44.4318, 26.1025),
        ("Centru — Piata Universitatii", 44.4358, 26.1025),
        ("Centru — Unirii", 44.4268, 26.1025),
        ("Centru — Magheru", 44.4380, 26.1020),
        ("Centru — Piata Romana", 44.4455, 26.0972),
        ("Centru — Piata Revolutiei", 44.4412, 26.0978),
        ("Centru — Amzei", 44.4435, 26.0948),
        ("Centru — Calea Dorobantilor", 44.4530, 26.0965),
        ("Old Town", 44.4315, 26.1020),
        ("Calea Victoriei", 44.4400, 26.0978),
        ("Cotroceni", 44.4230, 26.0580),
        ("Herastrau", 44.4780, 26.0820),
        ("Floreasca", 44.4720, 26.1050),
        ("Baneasa", 44.4850, 26.0780),
        ("Titan", 44.4150, 26.1520),
        ("Pantelimon", 44.4430, 26.1680),
        ("Drumul Taberei", 44.4100, 26.0340),
        ("Militari", 44.4180, 26.0380),
        ("Giurgiu Blvd", 44.4185, 26.1120),
        ("Rahova", 44.4050, 26.0680),
        ("Ferentari", 44.3980, 26.0880),
        ("Berceni", 44.3880, 26.1180),
        ("Piata Sudului", 44.3950, 26.1220),
        ("Dristor", 44.4080, 26.1180),
        ("Vitan", 44.4200, 26.1350),
        ("Colentina", 44.4620, 26.1420),
        ("Tei", 44.4480, 26.1280),
        ("Obor", 44.4480, 26.1380),
        ("Crangasi", 44.4420, 26.0480),
        ("Giulesti", 44.4620, 26.0520),
        ("Apaca", 44.4380, 26.0280),
        ("Militari Nord", 44.4280, 26.0180),
        ("Chitila Gate", 44.4880, 26.0280),
        ("Bucharest Nord", 44.4880, 26.0750),
        ("Pipera", 44.4920, 26.1180),
        ("Voluntari Edge", 44.5050, 26.1450),
        ("1 Mai", 44.4520, 26.0350),
        ("Romana Residences", 44.4020, 26.0450),
        ("Tineretului", 44.4120, 26.1050),
        ("Timpuri Noi", 44.4180, 26.1280),
    ),
    "Cluj-Napoca": (
        ("Centru — Piata Unirii", 46.7711, 23.6236),
        ("Centru — Piata Mihai Viteazu", 46.7689, 23.5898),
        ("Centru — Memorandumului", 46.7680, 23.5910),
        ("Centru — Piezisa", 46.7735, 23.5790),
        ("Centru — Avram Iancu", 46.7665, 23.5825),
        ("Centru — Observatorului", 46.7662, 23.5798),
        ("Centru — Piata Luca Arbore", 46.7702, 23.6278),
        ("Gheorgheni", 46.7695, 23.6380),
        ("Marasti", 46.7540, 23.6130),
        ("Zorilor", 46.7620, 23.5780),
        ("Iris", 46.7870, 23.6050),
        ("Intre Lacuri", 46.7790, 23.6450),
        ("Grigorescu", 46.7780, 23.5650),
        ("Manastur", 46.7570, 23.5550),
        ("Bulgaria", 46.7480, 23.5900),
        ("Buna Ziua", 46.7430, 23.5580),
        ("Dambu Rotund", 46.7830, 23.6180),
        ("Someșeni", 46.7930, 23.6350),
    ),
    "Craiova": (
        ("Centru", 44.3302, 23.7949),
        ("Centru — Piata Mihai Viteazu", 44.3278, 23.7942),
        ("Centru — Calea Unirii", 44.3320, 23.7975),
        ("Centru — Stadion", 44.3285, 23.7915),
        ("Centru — Scuar", 44.3315, 23.7928),
        ("Centru — Electroputere", 44.3295, 23.7990),
        ("Rovine", 44.3180, 23.8110),
        ("Brazda lui Novac", 44.3350, 23.8200),
        ("Facai", 44.3450, 23.7850),
        ("Sterea", 44.3220, 23.7750),
        ("Craiovita", 44.3380, 23.7650),
        ("Romanesti", 44.3120, 23.7980),
    ),
}

SPOTS_PER_NEIGHBORHOOD = 7

STATUSES = ("empty", "occupied", "correct", "violation", "illegal")
STATUS_WEIGHTS = (32, 26, 16, 14, 12)


def _price_hundredths(seed: int) -> int:
    """Uneven hourly rate in hundredths (2.15–9.87 Credits), stable per device id."""
    r = random.Random(42 + seed * 7919)
    whole = r.randint(2, 9)
    frac = r.randint(0, 99)
    if frac % 10 == 0:
        frac = (frac + r.randint(3, 17)) % 100
    if frac % 5 == 0 and r.random() < 0.55:
        frac = (frac + r.randint(2, 13)) % 100
    return whole * 100 + frac


def _schedule_hundredths(instant: int, seed: int) -> int:
    r = random.Random(17 + seed * 3571)
    discount = r.randint(7, 213)
    return max(215, instant - discount)


def _deposit_hundredths(seed: int) -> int:
    r = random.Random(99 + seed * 2017)
    whole = r.randint(2, 7)
    frac = r.choice(
        [
            r.randint(1, 99),
            r.randint(10, 99),
            r.randint(25, 97),
        ]
    )
    if frac % 10 == 0:
        frac = (frac + r.randint(4, 19)) % 100
    return whole * 100 + frac


def _device_status(device_id: int) -> str:
    r = random.Random(device_id * 13 + 7)
    return r.choices(STATUSES, weights=STATUS_WEIGHTS, k=1)[0]


def _append_demo_device(
    devices,
    *,
    dev_id: int,
    city: str,
    code: str,
    city_seq: int,
    zone: str,
    lat: float,
    lng: float,
    slot: int,
    base,
) -> int:
    spot_rng = random.Random(dev_id * 31 + slot)
    status = _device_status(dev_id)
    plate = None
    if status in ("occupied", "correct", "violation", "illegal"):
        plate = f"B-{spot_rng.randint(100, 999)}-{spot_rng.choice(['MAB', 'XYZ', 'ABC', 'KLM', 'PKR', 'GLS'])}"
    online = status != "empty" or slot % 4 != 0
    d = SimpleNamespace()
    d.id = dev_id
    d.name = f"{city} — {zone}"
    d.spot_label = f"{code}-{city_seq:03d}"
    d.assigned_plate = plate
    d.current_status = status
    d.is_online = online
    d.mac_address = f"DE:MO:{dev_id:04X}:00:01"
    d.last_seen = base - timedelta(seconds=30 if online else 4000)
    d.last_wifi = spot_rng.randint(55, 92) if online else None
    d.last_temp = round(spot_rng.uniform(45.0, 56.0), 1) if online else None
    d.created_at = base - timedelta(days=20 + (dev_id % 40))
    d.capture_requested = status in ("violation", "illegal") and slot % 3 == 0
    d.latitude = round(lat, 5)
    d.longitude = round(lng, 5)
    d.location_zone = zone
    d.notes = f"Demo bay in {city}"
    d.fines = SimpleNamespace(count=lambda: spot_rng.randint(0, 2))
    devices.append(d)
    return dev_id + 1


def build_demo_devices(now_fn):
    base = now_fn()
    devices = []
    dev_id = 200
    for city, _clat, _clng, _spread in CITIES:
        code = CITY_CODES[city]
        city_seq = 0
        for zone, nlat, nlng in CITY_NEIGHBORHOODS[city]:
            for slot in range(SPOTS_PER_NEIGHBORHOOD):
                spot_rng = random.Random(dev_id * 31 + slot)
                lat = nlat + spot_rng.uniform(-0.004, 0.004)
                lng = nlng + spot_rng.uniform(-0.005, 0.005)
                city_seq += 1
                dev_id = _append_demo_device(
                    devices,
                    dev_id=dev_id,
                    city=city,
                    code=code,
                    city_seq=city_seq,
                    zone=zone,
                    lat=lat,
                    lng=lng,
                    slot=slot,
                    base=base,
                )

        if city == "Bucharest":
            scatter = random.Random(8800)
            scatter_zones = (
                "Sector 1",
                "Sector 2",
                "Sector 3",
                "Sector 4",
                "Sector 5",
                "Sector 6",
            )
            for slot in range(42):
                lat = scatter.uniform(44.384, 44.506)
                lng = scatter.uniform(25.992, 26.178)
                zone = f"Citywide — {scatter_zones[slot % len(scatter_zones)]}"
                city_seq += 1
                dev_id = _append_demo_device(
                    devices,
                    dev_id=dev_id,
                    city=city,
                    code=code,
                    city_seq=city_seq,
                    zone=zone,
                    lat=lat,
                    lng=lng,
                    slot=slot + 100,
                    base=base,
                )

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
        inst = _price_hundredths(d.id)
        sched = _schedule_hundredths(inst, d.id)
        deposit = _deposit_hundredths(d.id)
        floor = min(inst, sched)
        ceiling = max(inst, sched)
        owner_min = max(200, floor - _rng.randint(0, 75))
        owner_max = min(999, ceiling + _rng.randint(40, 280))
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
            owner_min_tenths=owner_min,
            owner_max_tenths=owner_max,
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

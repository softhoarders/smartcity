"""Provision fixed local demo accounts (real DB users, not session fake data)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import config
import requests
from models import Device, User, UserPlate, db
import spots_service

DEMO2_EMAIL = "demo2"
DEMO2_PASSWORD = "demo123!"
DEMO2_NAME = "Demo2"
DEMO2_WALLET_HUNDREDTHS = 100_000

_bcrypt = None


def bind_bcrypt(bcrypt_instance) -> None:
    """Called from app startup so hashing does not circular-import app."""
    global _bcrypt
    _bcrypt = bcrypt_instance


def _bcrypt_impl():
    if _bcrypt is None:
        from app import bcrypt as app_bcrypt

        return app_bcrypt
    return _bcrypt


def _password_hash(password: str) -> str:
    return _bcrypt_impl().generate_password_hash(password).decode("utf-8")


def _password_ok(stored_hash: str, password: str) -> bool:
    return _bcrypt_impl().check_password_hash(stored_hash, password)


def normalize_plate(plate: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())


def is_demo2_login(identifier: str, password: str) -> bool:
    return identifier.strip().lower() in {DEMO2_EMAIL, DEMO2_NAME.lower()} and password == DEMO2_PASSWORD


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_demo2_mac() -> str | None:
    if config.DEMO2_PI_MAC:
        return config.DEMO2_PI_MAC
    url = (config.DEMO2_PI_URL or "").strip()
    if not url:
        return None
    try:
        resp = requests.get(url.rstrip("/") + "/", timeout=5)
        resp.raise_for_status()
        mac = (resp.json().get("mac_address") or "").strip().upper()
        return mac or None
    except requests.RequestException:
        return None


def _ensure_demo2_plate(user: User, plate_norm: str) -> None:
    row = UserPlate.query.filter_by(plate=plate_norm).first()
    if row is None:
        row = UserPlate(
            user_id=user.id,
            plate=plate_norm,
            verification_status="approved",
            verified_at=_utcnow(),
            verification_notes="Provisioned for demo2 Pi edge account",
        )
        db.session.add(row)
    elif row.user_id != user.id:
        raise RuntimeError(f"Plate {plate_norm} already belongs to user_id={row.user_id}")
    else:
        row.verification_status = "approved"
        row.verified_at = row.verified_at or _utcnow()

    if user.license_plate != plate_norm:
        user.license_plate = plate_norm


def _ensure_demo2_device(user: User, plate_norm: str) -> Device | None:
    mac = _resolve_demo2_mac()
    if not mac:
        return None

    device = Device.query.filter_by(mac_address=mac).first()
    spot_label = config.DEMO2_SPOT_LABEL or "Bay-A1"
    if device is None:
        device = Device(
            mac_address=mac,
            name=f"Pi {spot_label}",
            spot_label=spot_label,
            assigned_plate=plate_norm,
            owner_user_id=user.id,
            last_seen=_utcnow(),
        )
        db.session.add(device)
    else:
        device.spot_label = spot_label
        device.assigned_plate = plate_norm
        device.owner_user_id = user.id
        device.last_seen = device.last_seen or _utcnow()
        if not device.name:
            device.name = f"Pi {spot_label}"

    return device


def ensure_demo2_account() -> User:
    """Real driver account for Pi / edge testing — no synthetic portal data."""
    plate_norm = normalize_plate(config.DEMO2_PLATE)
    if not plate_norm:
        raise ValueError("DEMO2_PLATE is empty")

    user = User.query.filter(db.func.lower(User.email) == DEMO2_EMAIL).first()
    if user is None:
        user = User(
            email=DEMO2_EMAIL,
            password_hash=_password_hash(DEMO2_PASSWORD),
            license_plate=plate_norm,
            name=DEMO2_NAME,
            role="driver",
            verification_status="approved",
        )
        db.session.add(user)
        db.session.flush()
        spots_service.credit_spots(
            user,
            DEMO2_WALLET_HUNDREDTHS,
            "welcome",
            "Demo2 account welcome balance",
        )
    else:
        changed = False
        if not _password_ok(user.password_hash, DEMO2_PASSWORD):
            user.password_hash = _password_hash(DEMO2_PASSWORD)
            changed = True
        if user.role != "driver":
            user.role = "driver"
            changed = True
        if user.verification_status != "approved":
            user.verification_status = "approved"
            changed = True
        if (user.name or "").strip() != DEMO2_NAME:
            user.name = DEMO2_NAME
            changed = True

    _ensure_demo2_plate(user, plate_norm)
    device = _ensure_demo2_device(user, plate_norm)
    db.session.commit()

    if device is None:
        print(
            "[startup] demo2: plate provisioned but Pi MAC unknown "
            f"(set DEMO2_PI_MAC or ensure DEMO2_PI_URL is reachable: {config.DEMO2_PI_URL})",
            flush=True,
        )
    else:
        print(
            f"[startup] demo2: plate {plate_norm} -> device {device.mac_address} ({device.spot_label})",
            flush=True,
        )

    return user

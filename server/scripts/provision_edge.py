#!/usr/bin/env python3
"""Provision a Pi edge client and a regular (non-demo) driver account."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from app import app, normalize_plate  # noqa: E402
from models import Device, User, UserPlate, db  # noqa: E402
import bcrypt  # noqa: E402


def _utcnow():
    return datetime.now(timezone.utc)


def ensure_driver(email: str, password: str, name: str, plate: str) -> User:
    plate_norm = normalize_plate(plate)
    with app.app_context():
        user = User.query.filter_by(email=email.lower()).first()
        if user is None:
            user = User(
                email=email.lower(),
                password_hash=bcrypt.generate_password_hash(password).decode("utf-8"),
                license_plate=plate_norm,
                name=name,
                role="driver",
                verification_status="approved",
            )
            db.session.add(user)
            db.session.flush()
            print(f"[+] Created driver: {email}")
        else:
            print(f"[=] Driver exists: {email} (id={user.id})")

        row = UserPlate.query.filter_by(plate=plate_norm).first()
        if row is None:
            row = UserPlate(
                user_id=user.id,
                plate=plate_norm,
                verification_status="approved",
                verified_at=_utcnow(),
                verification_notes="Provisioned via scripts/provision_edge.py",
            )
            db.session.add(row)
            print(f"[+] Approved plate: {plate_norm}")
        elif row.user_id != user.id:
            raise SystemExit(f"Plate {plate_norm} already belongs to user_id={row.user_id}")
        else:
            row.verification_status = "approved"
            row.verified_at = row.verified_at or _utcnow()
            print(f"[=] Plate already on account: {plate_norm}")

        user.license_plate = plate_norm
        db.session.commit()
        return user


def fetch_pi_mac(pi_health_url: str) -> str:
    resp = requests.get(pi_health_url.rstrip("/") + "/", timeout=8)
    resp.raise_for_status()
    data = resp.json()
    mac = (data.get("mac_address") or "").strip().upper()
    if not mac:
        raise SystemExit(f"No mac_address in Pi health response: {data}")
    print(f"[+] Pi MAC from health: {mac}")
    return mac


def configure_device(
    mac: str,
    *,
    spot_label: str,
    assigned_plate: str,
    owner_user_id: int | None,
    name: str | None,
    capture_now: bool,
) -> Device:
    plate_norm = normalize_plate(assigned_plate)
    mac = mac.upper()
    with app.app_context():
        device = Device.query.filter_by(mac_address=mac).first()
        if device is None:
            device = Device(
                mac_address=mac,
                name=name or f"Pi-{mac[-5:].replace(':', '')}",
                spot_label=spot_label,
                assigned_plate=plate_norm,
                last_seen=_utcnow(),
                owner_user_id=owner_user_id,
            )
            db.session.add(device)
            print(f"[+] Registered device {mac}")
        else:
            if name:
                device.name = name
            device.spot_label = spot_label
            device.assigned_plate = plate_norm
            device.last_seen = _utcnow()
            if owner_user_id is not None:
                device.owner_user_id = owner_user_id
            print(f"[=] Updated device {mac} (id={device.id})")

        if capture_now:
            device.capture_requested = True
            print("[+] capture_now flag set")

        db.session.commit()
        return device


def wait_for_device(server_url: str, timeout: int) -> str | None:
    url = f"{server_url.rstrip('/')}/api/devices"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            devices = requests.get(url, timeout=5).json()
            if devices:
                mac = devices[0]["mac_address"]
                print(f"[+] Device appeared on server: {mac}")
                return mac
        except requests.RequestException as exc:
            print(f"[!] Poll failed: {exc}")
        time.sleep(5)
    return None


def main():
    parser = argparse.ArgumentParser(description="Provision Pi + regular driver")
    parser.add_argument("--email", default="driver@spotflow.local")
    parser.add_argument("--password", default="Spotflow2026!")
    parser.add_argument("--name", default="Test Driver")
    parser.add_argument("--plate", default="B123MAB")
    parser.add_argument("--spot", default="Bay-A1")
    parser.add_argument("--pi-url", default="http://10.142.182.127:3000", help="Pi health base URL")
    parser.add_argument("--mac", help="Device MAC (skip Pi health fetch)")
    parser.add_argument("--server", default="http://127.0.0.1:2026")
    parser.add_argument("--wait", type=int, default=0, help="Seconds to poll /api/devices for registration")
    parser.add_argument("--capture-now", action="store_true")
    args = parser.parse_args()

    user = ensure_driver(args.email, args.password, args.name, args.plate)

    mac = args.mac
    if not mac and args.pi_url:
        try:
            mac = fetch_pi_mac(args.pi_url)
        except requests.RequestException as exc:
            print(f"[!] Could not reach Pi at {args.pi_url}: {exc}")

    if not mac and args.wait > 0:
        print(f"[*] Waiting up to {args.wait}s for device registration...")
        mac = wait_for_device(args.server, args.wait)

    if not mac:
        print(
            "\n[!] No MAC available. Ensure the Pi can reach the server:\n"
            f"    PARKWATCH_SERVER={args.server}\n"
            "    Then re-run with --mac AA:BB:... or --wait 120"
        )
        sys.exit(1)

    device = configure_device(
        mac,
        spot_label=args.spot,
        assigned_plate=args.plate,
        owner_user_id=user.id,
        name=f"Pi {args.spot}",
        capture_now=args.capture_now,
    )
    print(
        f"\nDone.\n"
        f"  Driver: {args.email} / {args.password}\n"
        f"  Plate:  {normalize_plate(args.plate)}\n"
        f"  Device: id={device.id} mac={device.mac_address} spot={device.spot_label}\n"
        f"  Pi health: {args.pi_url}/\n"
    )


if __name__ == "__main__":
    main()

"""
communicator.py — REST client for communicating with the ParkWatch server.

Handles device registration, heartbeats, config fetching, and fine reporting.
Uses the device's MAC address as permanent identifier.
"""

import os
import uuid
import platform
import requests
import config


def get_mac_address() -> str:
    """
    Get the device's MAC address as a permanent unique identifier.

    On Linux (Raspberry Pi), reads from /sys/class/net/<iface>/address.
    Falls back to Python's uuid.getnode() on other platforms.

    Returns:
        MAC address in XX:XX:XX:XX:XX:XX format.
    """
    # Try reading from network interface (Linux/Pi)
    if platform.system() == "Linux":
        for iface in ("wlan0", "eth0", "end0"):
            path = f"/sys/class/net/{iface}/address"
            if os.path.exists(path):
                with open(path, "r") as f:
                    mac = f.read().strip().upper()
                    if mac and mac != "00:00:00:00:00:00":
                        print(f"[COMM] MAC from {iface}: {mac}")
                        return mac

    # Fallback: use uuid.getnode()
    raw = uuid.getnode()
    mac = ':'.join(f'{(raw >> (8 * i)) & 0xFF:02X}' for i in reversed(range(6)))
    print(f"[COMM] MAC from uuid: {mac}")
    return mac


def register_device(mac: str, name: str = None) -> dict | None:
    """
    Register this device with the server.

    Args:
        mac: Device MAC address.
        name: Optional human-readable name.

    Returns:
        Device dict from server, or None on failure.
    """
    url = f"{config.SERVER_URL}/api/devices/register"
    payload = {"mac_address": mac}
    if name:
        payload["name"] = name

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"[COMM] Registered: {data.get('name')} (ID: {data.get('id')})")
        return data
    except requests.RequestException as e:
        print(f"[COMM] Registration failed: {e}")
        return None


def send_heartbeat(mac: str, wifi: int = None, temp: float = None, spot_status: str = "empty") -> str | None:
    """Send a heartbeat to keep the device marked as online and return action if requested."""
    url = f"{config.SERVER_URL}/api/devices/{mac}/heartbeat"
    payload = {"spot_status": spot_status}
    if wifi is not None:
        payload["wifi_strength"] = wifi
    if temp is not None:
        payload["temperature"] = temp
        
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("action")
    except requests.RequestException as e:
        print(f"[COMM] Heartbeat failed: {e}")
    return None


def get_device_config(mac: str) -> dict | None:
    """
    Fetch device configuration from server (assigned plate, spot label, etc.).

    Returns:
        Config dict or None on failure.
    """
    url = f"{config.SERVER_URL}/api/devices/{mac}/config"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"[COMM] Config fetch failed: {e}")
        return None


def report_fine(mac: str, detected_plate: str, expected_plate: str,
                image_path: str, first_seen_iso: str,
                duration_minutes: int, confidence_score: float = 0.0) -> dict | None:
    """
    Report a plate mismatch (fine) to the server.

    Args:
        mac: Device MAC address.
        detected_plate: The plate actually read.
        expected_plate: The plate that should be there.
        image_path: Path to evidence image.
        first_seen_iso: ISO timestamp of first detection.
        duration_minutes: How long the wrong car has been there.
        confidence_score: Plate OCR confidence score.

    Returns:
        Fine dict from server, or None on failure.
    """
    url = f"{config.SERVER_URL}/api/fines"

    form_data = {
        "mac_address": mac,
        "detected_plate": detected_plate,
        "expected_plate": expected_plate,
        "first_seen": first_seen_iso,
        "duration_minutes": str(duration_minutes),
        "confidence_score": str(confidence_score),
    }

    files = {}
    if image_path and os.path.exists(image_path):
        files["image"] = (os.path.basename(image_path),
                          open(image_path, "rb"), "image/jpeg")

    try:
        resp = requests.post(url, data=form_data, files=files, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        print(f"[COMM] Fine reported: #{data.get('id')} — plate '{detected_plate}' "
              f"(expected '{expected_plate}'), {duration_minutes} min")
        return data
    except requests.RequestException as e:
        print(f"[COMM] Fine report failed: {e}")
        return None
    finally:
        if "image" in files:
            files["image"][1].close()

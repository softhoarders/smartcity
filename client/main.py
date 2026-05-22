"""
main.py — ParkWatch client entry point.

Runs the monitoring loop:
  1. Register with server (MAC-based identity)
  2. Start health endpoint on port 3000
  3. Loop: capture → detect plate → compare → report fine if mismatch
  4. Sleep based on time of day (10 min day / 30 min night)
"""

import os
import sys
import time
import shutil
import threading
from datetime import datetime, timedelta

from flask import Flask, jsonify

import config
from camera import capture_image, cleanup_old_captures
from plate_reader import read_plate
from communicator import (
    get_mac_address,
    register_device,
    send_heartbeat,
    get_device_config,
    report_fine,
)

# ---------------------------------------------------------------------------
# Health endpoint (lightweight Flask on port 3000)
# ---------------------------------------------------------------------------

health_app = Flask(__name__)
health_app.logger.disabled = True

# Shared state for health endpoint
_status = {
    "mac": None,
    "state": "starting",
    "last_capture": None,
    "last_plate": None,
    "assigned_plate": None,
    "cycle_count": 0,
    "spot_status": "empty",
}

def _update_weather_camera_settings():
    """Fetch weather data from Open-Meteo to adjust camera settings (simulated)."""
    try:
        # Using Bucharest coords as example
        resp = requests.get("https://api.open-meteo.com/v1/forecast?latitude=44.43&longitude=26.10&current_weather=true", timeout=5)
        if resp.status_code == 200:
            weather = resp.json().get("current_weather", {})
            code = weather.get("weathercode", 0)
            is_day = weather.get("is_day", 1)
            
            settings = "Normal"
            if is_day == 0:
                settings = "Night Vision (High ISO, Long Exposure)"
            elif code in [61, 63, 65, 80, 81, 82]: # Rain
                settings = "Rain Mode (High Contrast, Fast Shutter)"
                
            print(f"[CAM] Weather updated: Day={is_day}, Code={code} -> Applied: {settings}")
    except Exception as e:
        print(f"[CAM] Weather API error: {e}")


@health_app.route("/")
def health():
    return jsonify({
        "service": "parkwatch-client",
        "status": _status["state"],
        "mac_address": _status["mac"],
        "last_capture": _status["last_capture"],
        "last_detected_plate": _status["last_plate"],
        "assigned_plate": _status["assigned_plate"],
        "cycle_count": _status["cycle_count"],
        "uptime": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


def _start_health_server():
    """Start the health endpoint in a background thread."""
    health_app.run(
        host="0.0.0.0",
        port=config.CLIENT_PORT,
        debug=False,
        use_reloader=False,
    )

# ---------------------------------------------------------------------------
# Scheduling helpers
# ---------------------------------------------------------------------------

def _is_daytime() -> bool:
    """Check if current hour is within daytime range."""
    hour = datetime.now().hour
    return config.DAY_START_HOUR <= hour < config.DAY_END_HOUR


def _get_interval() -> int:
    """Get capture interval based on time of day."""
    return config.DAY_INTERVAL if _is_daytime() else config.NIGHT_INTERVAL


def _get_cpu_temp() -> float:
    """Read Raspberry Pi CPU temperature or return mock if not Linux."""
    try:
        if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_raw = f.read().strip()
                return round(float(temp_raw) / 1000.0, 1)
    except Exception as e:
        pass
    # Return realistic temperature variation around 42C
    import random
    return round(40.0 + random.random() * 5.0, 1)


def _get_wifi_strength() -> int:
    """Read Wi-Fi link quality or return mock/static value."""
    try:
        if os.path.exists("/proc/net/wireless"):
            with open("/proc/net/wireless", "r") as f:
                lines = f.readlines()
                if len(lines) > 2:
                    parts = lines[2].split()
                    link_quality = parts[2].replace('.', '')
                    return int(float(link_quality))
    except Exception as e:
        pass
    import random
    return random.randint(75, 95)


# ---------------------------------------------------------------------------
# Mismatch tracking
# ---------------------------------------------------------------------------

# Tracks unauthorized plates: {plate: first_seen_datetime}
_mismatch_tracker = {}


def _track_mismatch(detected_plate: str) -> tuple[str, int]:
    """
    Track how long a mismatched plate has been present.

    Returns:
        (first_seen_iso, duration_minutes)
    """
    now = datetime.now()

    if detected_plate not in _mismatch_tracker:
        _mismatch_tracker[detected_plate] = now

    first_seen = _mismatch_tracker[detected_plate]
    duration = int((now - first_seen).total_seconds() / 60)

    return first_seen.isoformat(), duration


def _clear_mismatch(plate: str = None):
    """Clear mismatch tracking when spot is valid or empty."""
    if plate and plate in _mismatch_tracker:
        del _mismatch_tracker[plate]
    elif plate is None:
        _mismatch_tracker.clear()

# ---------------------------------------------------------------------------
# Evidence management
# ---------------------------------------------------------------------------

def cleanup_old_evidence(max_days: int = 14):
    """Remove evidence files older than `max_days` locally."""
    cutoff = datetime.now() - timedelta(days=max_days)
    try:
        for f in os.listdir(config.EVIDENCE_DIR):
            if not f.endswith(".jpg"):
                continue
            path = os.path.join(config.EVIDENCE_DIR, f)
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            if mtime < cutoff:
                os.remove(path)
                print(f"[EVIDENCE] Purged old evidence: {f}")
    except Exception as e:
        print(f"[EVIDENCE] Cleanup error: {e}")

# ---------------------------------------------------------------------------
# Main monitoring loop
# ---------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("  ParkWatch Client v1.0")
    print("=" * 50)
    print(f"  Server: {config.SERVER_URL}")
    print(f"  Health port: {config.CLIENT_PORT}")
    print(f"  Camera index: {config.CAMERA_INDEX}")
    if config.TEST_IMAGE:
        print(f"  TEST MODE: using {config.TEST_IMAGE}")
    print("=" * 50)
    print()

    # 1. Get MAC address
    mac = get_mac_address()
    _status["mac"] = mac
    print(f"[MAIN] Device MAC: {mac}")

    # 2. Start health endpoint in background
    health_thread = threading.Thread(target=_start_health_server, daemon=True)
    health_thread.start()
    print(f"[MAIN] Health endpoint: http://0.0.0.0:{config.CLIENT_PORT}")

    # 3. Register with server (retry on failure)
    print("[MAIN] Registering with server...")
    _status["state"] = "registering"
    device_info = None

    while device_info is None:
        device_info = register_device(mac)
        if device_info is None:
            print("[MAIN] Server unreachable — retrying in 30s...")
            time.sleep(30)

    print(f"[MAIN] Registered as '{device_info.get('name')}' "
          f"(ID: {device_info.get('id')})")

    # 4. Main monitoring loop
    _status["state"] = "monitoring"
    print("[MAIN] Starting monitoring loop...")

    while True:
        try:
            _status["cycle_count"] += 1
            cycle = _status["cycle_count"]
            interval = _get_interval()
            time_mode = "DAY" if _is_daytime() else "NIGHT"

            print(f"\n{'='*40}")
            print(f"[MAIN] Cycle #{cycle} ({time_mode}, interval: {interval}s)")
            print(f"{'='*40}")

            # Send heartbeat with RPi stats
            wifi = _get_wifi_strength()
            temp = _get_cpu_temp()
            action = send_heartbeat(mac, wifi=wifi, temp=temp, spot_status=_status.get("spot_status", "empty"))
            force_capture = (action == "capture_now")
            if force_capture:
                print("[MAIN] ! SERVER REQUESTED IMMEDIATE CAPTURE !")
                
            # Periodically adjust camera based on weather
            if cycle % 30 == 1:
                _update_weather_camera_settings()

            # Fetch config (assigned plate)
            cfg = get_device_config(mac)
            assigned_plate = None
            if cfg:
                assigned_plate = cfg.get("assigned_plate")
                _status["assigned_plate"] = assigned_plate

            if not assigned_plate and not force_capture:
                print("[MAIN] No plate assigned — skipping capture.")
                time.sleep(interval)
                continue

            if assigned_plate:
                print(f"[MAIN] Assigned plate: {assigned_plate}")

            # Capture image
            _status["state"] = "capturing"
            image_path = capture_image()
            _status["last_capture"] = datetime.now().isoformat()

            if not image_path:
                print("[MAIN] Capture failed — skipping cycle.")
                _status["state"] = "monitoring"
                time.sleep(interval)
                continue

            # Detect plate
            _status["state"] = "processing"
            print("[MAIN] Running plate detection...")
            detected_plate, confidence = read_plate(image_path)
            _status["last_plate"] = detected_plate

            if detected_plate is None:
                # Could be empty spot or plate not readable
                print("[MAIN] No plate detected — spot may be empty.")
                _status["spot_status"] = "empty"
                _clear_mismatch()
                _status["state"] = "monitoring"
                time.sleep(interval)
                continue

            if not assigned_plate:
                print(f"[MAIN] Captured plate '{detected_plate}' (No assigned plate to compare against).")
            else:
                print(f"[MAIN] Detected: '{detected_plate}' vs Expected: '{assigned_plate}'")

                # Compare plates (normalize for comparison)
                detected_norm = detected_plate.replace(" ", "").upper()
                assigned_norm = assigned_plate.replace(" ", "").upper()

                if detected_norm == assigned_norm:
                    print("[MAIN] ✓ Correct plate — no action needed.")
                    _status["spot_status"] = "correct"
                    _clear_mismatch()
                else:
                    print("[MAIN] ✗ MISMATCH — logging fine!")
                    _status["spot_status"] = "illegal"
                    first_seen_iso, duration = _track_mismatch(detected_plate)
                    
                    # Copy evidence image for local storage before reporting
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    evidence_filename = f"fine_{mac.replace(':', '')}_{timestamp}.jpg"
                    evidence_path = os.path.join(config.EVIDENCE_DIR, evidence_filename)
                    
                    try:
                        shutil.copy2(image_path, evidence_path)
                        print(f"[MAIN] Saved local evidence to {evidence_filename}")
                    except Exception as e:
                        print(f"[MAIN] Error saving local evidence: {e}")
                        evidence_path = image_path # Fallback to original for reporting
                    
                    report_fine(
                        mac=mac,
                        detected_plate=detected_plate,
                        expected_plate=assigned_plate,
                        image_path=evidence_path,  # Upload the local evidence copy
                        first_seen_iso=first_seen_iso,
                        duration_minutes=duration,
                        confidence_score=confidence,
                    )

            # Delete the temporary capture image to save space
            # We only keep evidence of actual fines now.
            if os.path.exists(image_path) and image_path != config.TEST_IMAGE:
                # Do not delete if it's the test image
                if not config.TEST_IMAGE or os.path.abspath(image_path) != os.path.abspath(config.TEST_IMAGE):
                    try:
                         os.remove(image_path)
                    except Exception as e:
                         pass

            # Cleanup old captures and old evidence periodically
            if cycle % 10 == 0:
                cleanup_old_captures() # Still clean up any orphaned temp captures
            
            # Run deep evidence cleanup once per day (roughly every 144 cycles for 10 min interval)
            if cycle % 144 == 0:
                cleanup_old_evidence(14)

            _status["state"] = "monitoring"
            if force_capture:
                print("[MAIN] Immediate capture execution complete. Resuming normal interval in 5s...")
                time.sleep(5)
            else:
                print(f"[MAIN] Sleeping {interval}s ({time_mode} mode)...")
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n[MAIN] Shutting down...")
            sys.exit(0)
        except Exception as e:
            print(f"[MAIN] Error in cycle: {e}")
            _status["state"] = "error"
            time.sleep(60)  # Wait a bit after errors


if __name__ == "__main__":
    main()

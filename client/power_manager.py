"""
power_manager.py — DietPi / Raspberry Pi energy tuning for ParkWatch.

Applies headless power-saving defaults and switches CPU governor between
idle (between captures) and active (camera + OCR) profiles.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time

import config

_IS_LINUX = platform.system() == "Linux"
_PROFILE = "idle"


def is_raspberry_pi() -> bool:
    if not _IS_LINUX:
        return False
    try:
        with open("/proc/device-tree/model", "r", encoding="utf-8") as f:
            return "raspberry pi" in f.read().lower()
    except OSError:
        return os.path.exists("/sys/firmware/devicetree/base/model")


def _run(cmd: list[str], check: bool = False) -> bool:
    try:
        subprocess.run(cmd, check=check, capture_output=True, timeout=8)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _write_sys(path: str, value: str) -> bool:
    if not _IS_LINUX or not os.path.exists(path):
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)
        return True
    except OSError:
        return False


def set_cpu_governor(governor: str) -> None:
    for cpu in range(4):
        path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"
        if os.path.exists(path):
            _write_sys(path, governor)
            break


def hdmi_power(off: bool = True) -> None:
    if not is_raspberry_pi():
        return
    _run(["vcgencmd", "display_power", "0" if off else "1"])


def wifi_power_save(enable: bool = True) -> None:
    if not _IS_LINUX:
        return
    for iface in ("wlan0", "end0"):
        if os.path.exists(f"/sys/class/net/{iface}"):
            _run(["iw", "dev", iface, "set", "power_save", "on" if enable else "off"])
            break


def usb_autosuspend(enable: bool = True) -> None:
    autosuspend = "/sys/bus/usb/devices/usb1/power/autosuspend"
    control = "/sys/bus/usb/devices/usb1/power/control"
    if enable:
        _write_sys(autosuspend, "2")
        _write_sys(control, "auto")
    else:
        _write_sys(control, "on")


def apply_install_defaults() -> None:
    """One-time DietPi-friendly tweaks (safe to run from install.sh)."""
    if not config.ENERGY_SAVE or not _IS_LINUX:
        print("[POWER] Energy save disabled or not on Linux — skipping install tuning.")
        return

    print("[POWER] Applying headless energy defaults...")
    hdmi_power(True)
    wifi_power_save(True)

    # Prefer powersave between cycles; ondemand when processing.
    set_cpu_governor("powersave")

    swappiness = "/proc/sys/vm/swappiness"
    if os.path.exists(swappiness):
        _write_sys(swappiness, "10")

    print("[POWER] Install defaults applied.")


def set_active_mode() -> None:
    global _PROFILE
    if not config.ENERGY_SAVE:
        return
    _PROFILE = "active"
    set_cpu_governor("ondemand")
    usb_autosuspend(False)


def set_idle_mode() -> None:
    global _PROFILE
    if not config.ENERGY_SAVE:
        return
    _PROFILE = "idle"
    set_cpu_governor("powersave")
    usb_autosuspend(True)
    wifi_power_save(True)


def energy_wait(seconds: int) -> None:
    """
    Sleep between capture cycles in short chunks so systemd can stop the service
    promptly and the SoC can stay in a low-power state longer.
    """
    if seconds <= 0:
        return
    set_idle_mode()
    chunk = max(15, min(60, config.SLEEP_CHUNK_SECONDS))
    remaining = seconds
    while remaining > 0:
        step = min(chunk, remaining)
        time.sleep(step)
        remaining -= step


def apply_runtime_defaults() -> None:
    if config.ENERGY_SAVE and is_raspberry_pi():
        print("[POWER] Raspberry Pi detected — energy-saving profile enabled.")
        apply_install_defaults()
    set_idle_mode()

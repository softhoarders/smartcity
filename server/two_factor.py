"""Simulated TOTP-style 2FA (no real SMS/authenticator app required)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
import time


def generate_secret() -> str:
    return secrets.token_hex(20)


def _counter(period: int = 30) -> int:
    return int(time.time()) // period


def current_code(secret: str, period: int = 30) -> str:
    """Six-digit simulated authenticator code for the current time window."""
    if not secret:
        return "000000"
    counter = _counter(period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % 1_000_000).zfill(6)


def verify_code(secret: str, code: str, *, period: int = 30, window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    base = _counter(period)
    for step in range(-window, window + 1):
        msg = struct.pack(">Q", base + step)
        digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha1).digest()
        off = digest[-1] & 0x0F
        truncated = struct.unpack(">I", digest[off : off + 4])[0] & 0x7FFFFFFF
        if str(truncated % 1_000_000).zfill(6) == code:
            return True
    return False


def seconds_remaining(period: int = 30) -> int:
    return period - (int(time.time()) % period)


def verify_mock_login_pin(code: str) -> bool:
    """Check the fixed mock email code used at sign-in."""
    import config

    entered = (code or "").strip().replace(" ", "")
    return entered == config.MOCK_LOGIN_2FA_PIN

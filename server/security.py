"""Lightweight security helpers — rate limits, headers, API keys."""

from __future__ import annotations

import time
from collections import defaultdict
from functools import wraps
from threading import Lock

from flask import abort, request, session

import config

_lock = Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def check_rate_limit(scope: str, limit: int | None = None, window_seconds: int | None = None) -> bool:
    """Return True if request is allowed."""
    limit = limit if limit is not None else config.RATE_LIMIT_DEFAULT
    window_seconds = window_seconds if window_seconds is not None else config.RATE_LIMIT_WINDOW_SECONDS
    key = f"{scope}:{client_ip()}"
    now = time.time()
    with _lock:
        hits = [t for t in _buckets[key] if now - t < window_seconds]
        if len(hits) >= limit:
            _buckets[key] = hits
            return False
        hits.append(now)
        _buckets[key] = hits
        return True


def rate_limit(scope: str, limit: int | None = None, window_seconds: int | None = None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not check_rate_limit(scope, limit, window_seconds):
                abort(429, description="Too many requests. Try again shortly.")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if config.FORCE_HTTPS:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def configure_session_cookies(app):
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if config.FORCE_HTTPS:
        app.config["SESSION_COOKIE_SECURE"] = True


def require_n8n_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = config.N8N_API_KEY
        if not expected:
            abort(503, description="n8n API is not configured (set N8N_API_KEY).")
        provided = request.headers.get("X-Spotflow-Api-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not provided or not _constant_time_eq(provided, expected):
            abort(401, description="Invalid API key.")
        return fn(*args, **kwargs)

    return wrapper


def require_device_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = config.DEVICE_API_KEY
        if not expected:
            return fn(*args, **kwargs)
        provided = request.headers.get("X-Device-Api-Key", "")
        if not _constant_time_eq(provided, expected):
            abort(401, description="Invalid device API key.")
        return fn(*args, **kwargs)

    return wrapper


def _constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


def verify_webhook_signature(body: bytes, header_value: str | None) -> bool:
    secret = config.N8N_WEBHOOK_SECRET
    if not secret:
        return True
    if not header_value or not header_value.startswith("sha256="):
        return False
    import hashlib
    import hmac

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return _constant_time_eq(header_value[7:], expected)


def login_attempt_allowed() -> bool:
    return check_rate_limit(
        "login",
        limit=config.RATE_LIMIT_LOGIN_ATTEMPTS,
        window_seconds=config.RATE_LIMIT_LOGIN_WINDOW,
    )


def record_failed_login():
    check_rate_limit("login_fail", limit=config.RATE_LIMIT_LOGIN_ATTEMPTS, window_seconds=config.RATE_LIMIT_LOGIN_WINDOW)


def pending_2fa_valid() -> bool:
    exp = session.get("pending_2fa_exp")
    if not exp:
        return False
    return time.time() < float(exp)


def clear_pending_2fa():
    session.pop("pending_2fa_user_id", None)
    session.pop("pending_2fa_exp", None)
    session.pop("pending_2fa_remember", None)
    session.pop("pending_2fa_email", None)
    session.pop("pending_2fa_demo", None)
    session.pop("pending_2fa_demo_role", None)

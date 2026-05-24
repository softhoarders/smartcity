"""Provision fixed local demo accounts (real DB users, not session fake data)."""

from __future__ import annotations

from models import User, db
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


def is_demo2_login(identifier: str, password: str) -> bool:
    return identifier.strip().lower() in {DEMO2_EMAIL, DEMO2_NAME.lower()} and password == DEMO2_PASSWORD


def ensure_demo2_account() -> User:
    """Real driver account for Pi / edge testing — no synthetic portal data."""
    user = User.query.filter(db.func.lower(User.email) == DEMO2_EMAIL).first()
    if user is None:
        user = User(
            email=DEMO2_EMAIL,
            password_hash=_password_hash(DEMO2_PASSWORD),
            license_plate="",
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
        db.session.commit()
        return user

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
    if changed:
        db.session.commit()
    return user

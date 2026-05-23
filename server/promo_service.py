"""Promo and referral code validation and redemption."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

import config
from models import db, PromoCode, ReferralCode, ReferralRedemption, User
import spots_service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def ensure_default_promos():
    defaults = [
        ("WELCOME10", "topup_bonus", 10, 0),
        ("SPOTFLOW15", "topup_bonus", 15, 0),
        ("PARK20", "topup_bonus", 0, 20),
    ]
    for code, kind, pct, bonus in defaults:
        if not PromoCode.query.filter_by(code=code).first():
            db.session.add(
                PromoCode(
                    code=code,
                    kind=kind,
                    bonus_percent=pct,
                    bonus_spots=bonus,
                    max_uses=10_000,
                    active=True,
                )
            )
    db.session.commit()


def validate_promo(code: str) -> tuple[PromoCode | None, str | None]:
    norm = normalize_code(code)
    if not norm:
        return None, "Enter a promo code."
    promo = PromoCode.query.filter_by(code=norm, active=True).first()
    if not promo:
        return None, "Promo code not found or inactive."
    if promo.expires_at and promo.expires_at.replace(tzinfo=timezone.utc) < _utcnow():
        return None, "This promo code has expired."
    if promo.max_uses is not None and promo.uses_count >= promo.max_uses:
        return None, "This promo code has reached its usage limit."
    return promo, None


def apply_topup_promo(user: User, base_spots: int, code: str) -> tuple[int, str]:
    promo, err = validate_promo(code)
    if err:
        raise ValueError(err)
    if promo.kind != "topup_bonus":
        raise ValueError("This code is not valid for top-up.")
    bonus = int(promo.bonus_spots or 0)
    if promo.bonus_percent:
        bonus += max(0, (base_spots * int(promo.bonus_percent)) // 100)
    if bonus <= 0:
        raise ValueError("This promo does not add a bonus for this amount.")
    promo.uses_count = int(promo.uses_count or 0) + 1
    spots_service.credit_spots(
        user,
        bonus,
        "promo_bonus",
        f"Promo {promo.code} (+{bonus} {config.WALLET_CURRENCY_NAME})",
    )
    db.session.commit()
    return bonus, promo.code


def get_or_create_referral_code(user: User) -> str:
    row = ReferralCode.query.filter_by(user_id=user.id).first()
    if row:
        return row.code
    base = normalize_code(user.email.split("@")[0])[:8] or "USER"
    code = f"{base}{user.id}"[:12]
    while ReferralCode.query.filter_by(code=code).first():
        code = f"{base}{secrets.token_hex(2).upper()}"[:12]
    row = ReferralCode(user_id=user.id, code=code)
    db.session.add(row)
    db.session.commit()
    return code


def redeem_referral_on_signup(new_user: User, code: str) -> bool:
    norm = normalize_code(code)
    if not norm:
        return False
    ref = ReferralCode.query.filter_by(code=norm).first()
    if not ref or ref.user_id == new_user.id:
        return False
    if ReferralRedemption.query.filter_by(referee_user_id=new_user.id).first():
        return False
    referrer = User.query.get(ref.user_id)
    if not referrer:
        return False

    new_user.referred_by_code = norm
    db.session.add(ReferralRedemption(referral_code_id=ref.id, referee_user_id=new_user.id))
    ref.uses_count = int(ref.uses_count or 0) + 1

    ref_bonus = config.REFERRAL_BONUS_REFERRER
    new_bonus = config.REFERRAL_BONUS_REFEREE
    if ref_bonus > 0:
        spots_service.credit_spots(
            referrer,
            ref_bonus,
            "referral_bonus",
            f"Referral bonus — {new_user.email}",
        )
    if new_bonus > 0:
        spots_service.credit_spots(
            new_user,
            new_bonus,
            "referral_welcome",
            f"Welcome bonus (referral {norm})",
        )
    db.session.commit()
    return True

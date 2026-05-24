"""Promo and referral code validation and redemption."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

import config
import spot_prices
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
    bonus = spot_prices.credits_to_hundredths(int(promo.bonus_spots or 0))
    if promo.bonus_percent:
        bonus += max(0, (base_spots * int(promo.bonus_percent)) // 100)
    if bonus <= 0:
        raise ValueError("This promo does not add a bonus for this amount.")
    promo.uses_count = int(promo.uses_count or 0) + 1
    spots_service.credit_spots(
        user,
        bonus,
        "promo_bonus",
        f"Promo {promo.code} (+{spot_prices.format_credits(bonus)} {config.WALLET_CURRENCY_NAME})",
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


def list_owner_promos(user_id: int, listing_id: int) -> list[PromoCode]:
    return (
        PromoCode.query.filter_by(owner_user_id=user_id, listing_id=listing_id, active=True)
        .order_by(PromoCode.created_at.desc())
        .all()
    )


def create_owner_promo(
    user: User,
    listing_id: int,
    *,
    code: str,
    kind: str,
    bonus_percent: int = 0,
    bonus_spots: int = 0,
    max_uses: int | None = 100,
    label: str | None = None,
) -> PromoCode:
    norm = normalize_code(code)
    if len(norm) < 4:
        raise ValueError("Code must be at least 4 characters.")
    if PromoCode.query.filter_by(code=norm).first():
        raise ValueError("That code is already taken.")
    if kind not in ("booking_discount", "topup_bonus"):
        raise ValueError("Invalid promo type.")
    if kind == "booking_discount" and bonus_percent <= 0 and bonus_spots <= 0:
        raise ValueError("Set a percent or credit discount for bookings.")
    row = PromoCode(
        code=norm,
        kind=kind,
        bonus_percent=max(0, int(bonus_percent)),
        bonus_spots=max(0, int(bonus_spots)),
        max_uses=max_uses,
        owner_user_id=user.id,
        listing_id=listing_id,
        label=(label or "").strip() or None,
        active=True,
    )
    db.session.add(row)
    db.session.commit()
    return row


def apply_booking_promo(listing_id: int, base_credits: int, code: str) -> tuple[int, PromoCode | None]:
    """Return (final_credits, promo) after optional listing-scoped booking discount."""
    promo, err = validate_promo(code)
    if err:
        raise ValueError(err)
    if promo.kind != "booking_discount":
        raise ValueError("This code is for bookings only.")
    if promo.listing_id and promo.listing_id != listing_id:
        raise ValueError("This code is not valid for this spot.")
    total = int(base_credits)
    if promo.bonus_percent:
        total = max(100, total - (total * int(promo.bonus_percent)) // 100)
    if promo.bonus_spots:
        total = max(100, total - spot_prices.credits_to_hundredths(int(promo.bonus_spots)))
    promo.uses_count = int(promo.uses_count or 0) + 1
    db.session.commit()
    return total, promo


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

    ref_bonus = spot_prices.credits_to_hundredths(config.REFERRAL_BONUS_REFERRER)
    new_bonus = spot_prices.credits_to_hundredths(config.REFERRAL_BONUS_REFEREE)
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

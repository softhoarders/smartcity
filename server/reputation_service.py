"""Cross-property parking reputation (trust passport) for renters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import config
from models import Fine, SpotBooking, User, UserParkingReputation, UserPlate, db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _tier_for_score(score: int) -> str:
    score = max(0, min(100, int(score)))
    if score < config.REPUTATION_TIER_FLAGGED_MAX:
        return "flagged"
    if score < config.REPUTATION_TIER_RESTRICTED_MAX:
        return "restricted"
    if score < config.REPUTATION_TIER_GOOD_MAX:
        return "new"
    if score < config.REPUTATION_TIER_TRUSTED_MAX:
        return "good"
    if score < config.REPUTATION_TIER_EXCELLENT_MAX:
        return "trusted"
    return "excellent"


def _tier_label(tier: str) -> str:
    return {
        "flagged": "Flagged",
        "restricted": "Restricted",
        "new": "New driver",
        "good": "Good standing",
        "trusted": "Trusted",
        "excellent": "Excellent",
    }.get(tier, tier.replace("_", " ").title())


def _user_plate_set(user: User) -> set[str]:
    plates = {p.upper().replace(" ", "").replace("-", "") for p in user.plate_values(approved_only=False)}
    return {"".join(ch for ch in p if ch.isalnum()) for p in plates if p}


def _normalize_plate(plate: str | None) -> str:
    if not plate:
        return ""
    return "".join(ch for ch in plate.upper() if ch.isalnum())


def _aggregate_booking_stats(user_id: int) -> dict[str, int]:
    rows = SpotBooking.query.filter_by(renter_id=user_id).all()
    completed = 0
    rejected = 0
    cancelled = 0
    on_time = 0
    late = 0
    for b in rows:
        st = (b.status or "").lower()
        if st == "completed":
            completed += 1
            on_time += 1
        elif st == "rejected":
            rejected += 1
        elif st in ("cancelled", "canceled"):
            cancelled += 1
        elif st == "no_show":
            late += 0
    total = len(rows)
    no_shows = rejected
    return {
        "total_bookings": total,
        "completed_bookings": completed,
        "on_time_departures": on_time,
        "late_departures": late,
        "no_shows": no_shows,
        "cancelled_bookings": cancelled,
    }


def _aggregate_appeal_stats(user: User) -> dict[str, int]:
    plates = _user_plate_set(user)
    if not plates:
        return {
            "appeals_filed": 0,
            "appeals_won": 0,
            "appeals_lost": 0,
            "false_appeals": 0,
        }
    filed = won = lost = false = 0
    for fine in Fine.query.all():
        expected = _normalize_plate(fine.expected_plate)
        if expected not in plates:
            continue
        appeal = (fine.appeal_status or "none").lower()
        if appeal == "none":
            continue
        filed += 1
        if appeal == "approved":
            won += 1
        elif appeal in ("rejected_by_ai", "rejected_human"):
            lost += 1
            false += 1
        elif appeal in ("pending_ai", "pending_human"):
            pass
    return {
        "appeals_filed": filed,
        "appeals_won": won,
        "appeals_lost": lost,
        "false_appeals": false,
    }


def _compute_trust_score(
    *,
    completed: int,
    total: int,
    on_time: int,
    no_shows: int,
    appeals_filed: int,
    appeals_won: int,
    false_appeals: int,
) -> int:
    if total == 0 and appeals_filed == 0:
        return config.REPUTATION_DEFAULT_NEW_SCORE

    completion_rate = completed / max(1, total)
    on_time_rate = on_time / max(1, completed) if completed else 0.7
    no_show_rate = no_shows / max(1, total)
    false_appeal_rate = false_appeals / max(1, appeals_filed)
    appeal_win_rate = appeals_won / max(1, appeals_filed)

    score = (
        50.0
        + completion_rate * 28.0
        + on_time_rate * 18.0
        - no_show_rate * 32.0
        - false_appeal_rate * 22.0
        + appeal_win_rate * 8.0
    )
    return int(max(0, min(100, round(score))))


def _pct(num: int, denom: int) -> int:
    if denom <= 0:
        return 0
    return int(round(100 * num / denom))


def recompute_for_user(user: User) -> UserParkingReputation:
    booking = _aggregate_booking_stats(user.id)
    appeal = _aggregate_appeal_stats(user)

    trust = _compute_trust_score(
        completed=booking["completed_bookings"],
        total=booking["total_bookings"],
        on_time=booking["on_time_departures"],
        no_shows=booking["no_shows"],
        appeals_filed=appeal["appeals_filed"],
        appeals_won=appeal["appeals_won"],
        false_appeals=appeal["false_appeals"],
    )
    tier = _tier_for_score(trust)

    row = UserParkingReputation.query.filter_by(user_id=user.id).first()
    if not row:
        row = UserParkingReputation(user_id=user.id)
        db.session.add(row)

    row.trust_score = trust
    row.tier = tier
    row.completed_bookings = booking["completed_bookings"]
    row.total_bookings = booking["total_bookings"]
    row.on_time_departures = booking["on_time_departures"]
    row.late_departures = booking["late_departures"]
    row.no_shows = booking["no_shows"]
    row.appeals_filed = appeal["appeals_filed"]
    row.appeals_won = appeal["appeals_won"]
    row.appeals_lost = appeal["appeals_lost"]
    row.false_appeals = appeal["false_appeals"]
    row.updated_at = _utcnow()
    return row


def get_or_create_reputation(user: User, *, recompute: bool = True) -> UserParkingReputation:
    row = UserParkingReputation.query.filter_by(user_id=user.id).first()
    if not row or recompute:
        row = recompute_for_user(user)
        db.session.commit()
    return row


def passport_dict(rep: UserParkingReputation | dict[str, Any]) -> dict[str, Any]:
    if isinstance(rep, dict):
        data = rep
    else:
        total = rep.total_bookings or 0
        completed = rep.completed_bookings or 0
        data = {
            "trust_score": rep.trust_score,
            "tier": rep.tier,
            "tier_label": _tier_label(rep.tier),
            "completed_bookings": completed,
            "total_bookings": total,
            "on_time_departures": rep.on_time_departures or 0,
            "late_departures": rep.late_departures or 0,
            "no_shows": rep.no_shows or 0,
            "appeals_filed": rep.appeals_filed or 0,
            "appeals_won": rep.appeals_won or 0,
            "appeals_lost": rep.appeals_lost or 0,
            "false_appeals": rep.false_appeals or 0,
            "on_time_pct": _pct(rep.on_time_departures or 0, max(1, completed)),
            "no_show_pct": _pct(rep.no_shows or 0, max(1, total)),
            "appeal_win_pct": _pct(rep.appeals_won or 0, max(1, rep.appeals_filed or 0)),
            "false_appeal_pct": _pct(rep.false_appeals or 0, max(1, rep.appeals_filed or 0)),
            "completion_pct": _pct(completed, max(1, total)),
        }
    data.setdefault("tier_label", _tier_label(data.get("tier", "new")))
    return data


def demo_passport() -> dict[str, Any]:
    return passport_dict(
        {
            "trust_score": 82,
            "tier": "trusted",
            "tier_label": _tier_label("trusted"),
            "completed_bookings": 14,
            "total_bookings": 16,
            "on_time_departures": 13,
            "late_departures": 1,
            "no_shows": 1,
            "appeals_filed": 3,
            "appeals_won": 2,
            "appeals_lost": 1,
            "false_appeals": 0,
            "on_time_pct": 93,
            "no_show_pct": 6,
            "appeal_win_pct": 67,
            "false_appeal_pct": 0,
            "completion_pct": 88,
        }
    )


def get_passport(user: User, *, is_demo: bool = False) -> dict[str, Any]:
    if is_demo or not user.id or user.id <= 0:
        return demo_passport()
    rep = get_or_create_reputation(user, recompute=False)
    if (rep.total_bookings or 0) == 0 and (rep.appeals_filed or 0) == 0:
        rep = get_or_create_reputation(user, recompute=True)
    return passport_dict(rep)


def invalidate_and_recompute(user_id: int) -> None:
    user = User.query.get(user_id)
    if user and user.id > 0:
        recompute_for_user(user)
        db.session.commit()


def find_user_for_fine(fine: Fine) -> User | None:
    plate = _normalize_plate(fine.expected_plate)
    if not plate:
        return None
    plate_raw = (fine.expected_plate or "").strip().upper()
    row = UserPlate.query.filter_by(plate=plate_raw).first()
    if not row:
        row = UserPlate.query.filter(
            UserPlate.plate.in_([plate_raw, plate_raw.replace("-", "")])
        ).first()
    if row:
        return row.user
    for user in User.query.filter_by(role="driver").all():
        if plate in _user_plate_set(user):
            return user
    return None


def check_booking_eligibility(user: User, listing, *, is_demo: bool = False) -> tuple[bool, str | None]:
    passport = get_passport(user, is_demo=is_demo)
    score = passport["trust_score"]
    min_trust = int(getattr(listing, "min_trust_score", 0) or 0)

    if score < config.REPUTATION_BLOCK_BELOW:
        return False, (
            f"Your parking trust score is {score} (minimum {config.REPUTATION_BLOCK_BELOW} to book). "
            "Complete rentals on time and avoid disputed appeals to improve your score."
        )

    if min_trust and score < min_trust:
        return False, (
            f"This spot requires trust {min_trust}+ for instant booking. "
            f"Your score is {score} — try a spot with lower requirements or request manual approval."
        )

    if getattr(listing, "approval_mode", "auto") == "auto" and score < config.REPUTATION_MIN_AUTO_BOOK:
        return False, (
            f"Instant booking needs trust {config.REPUTATION_MIN_AUTO_BOOK}+ (yours: {score}). "
            "Choose a manual-approval listing or build your reputation with completed rentals."
        )

    return True, None


def record_booking_completed(booking: SpotBooking) -> None:
    if booking.renter_id:
        invalidate_and_recompute(booking.renter_id)


def record_booking_no_show(booking: SpotBooking) -> None:
    booking.status = "no_show"
    if booking.renter_id:
        invalidate_and_recompute(booking.renter_id)


def record_appeal_resolved(fine: Fine) -> None:
    user = find_user_for_fine(fine)
    if user:
        invalidate_and_recompute(user.id)

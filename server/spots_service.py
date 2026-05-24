"""Spots wallet, subscriptions, and parking bookings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
import spot_prices
from models import db, Device, SpotBooking, SpotListing, SpotTransaction, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def user_balance(user: User) -> int:
    return int(user.spots_balance or 0)


def record_transaction(user: User, amount: int, kind: str, description: str, reference_id: int | None = None):
    tx = SpotTransaction(
        user_id=user.id,
        amount=amount,
        kind=kind,
        description=description,
        reference_id=reference_id,
    )
    db.session.add(tx)
    return tx


def credit_spots(user: User, amount: int, kind: str, description: str, reference_id: int | None = None) -> int:
    if amount <= 0:
        raise ValueError("Credit amount must be positive")
    user.spots_balance = user_balance(user) + amount
    record_transaction(user, amount, kind, description, reference_id)
    return user.spots_balance


def debit_spots(user: User, amount: int, kind: str, description: str, reference_id: int | None = None) -> int:
    if amount <= 0:
        raise ValueError("Debit amount must be positive")
    if user_balance(user) < amount:
        raise ValueError(f"Insufficient {config.WALLET_CURRENCY_NAME.lower()} balance")
    user.spots_balance = user_balance(user) - amount
    record_transaction(user, -amount, kind, description, reference_id)
    return user.spots_balance


def transfer_spots(
    from_user: User,
    to_user: User,
    amount: int,
    kind_debit: str,
    kind_credit: str,
    description: str,
    reference_id: int | None = None,
):
    debit_spots(from_user, amount, kind_debit, description, reference_id)
    credit_spots(to_user, amount, kind_credit, description, reference_id)


def lei_to_spots(lei: int) -> int:
    return spot_prices.credits_to_hundredths(int(lei) * config.SPOT_TO_LEI)


def calculate_instant_total(listing: SpotListing, hours: int) -> int:
    hours = max(config.MIN_INSTANT_HOURS, min(hours, config.MAX_BOOKING_HOURS))
    return spot_prices.instant_total_billable(listing, hours)


def calculate_scheduled_total(listing: SpotListing, starts_at: datetime, ends_at: datetime) -> tuple[int, int, int]:
    """Returns (total_spots, deposit_spots, hours)."""
    delta = ends_at - starts_at
    hours = max(1, int(delta.total_seconds() // 3600) or 1)
    hours = min(hours, config.MAX_BOOKING_HOURS)
    total, deposit = spot_prices.schedule_total_billable(listing, hours)
    return total, deposit, hours


def active_booking_for_device(device_id: int, at: datetime | None = None) -> SpotBooking | None:
    at = _aware(at or _utcnow())
    return (
        SpotBooking.query.join(SpotListing)
        .filter(
            SpotListing.device_id == device_id,
            SpotBooking.status.in_(("approved", "active")),
            SpotBooking.starts_at <= at,
            SpotBooking.ends_at > at,
        )
        .order_by(SpotBooking.starts_at.desc())
        .first()
    )


def effective_assigned_plate(device: Device, at: datetime | None = None) -> str | None:
    """Plate allowed to park: active booking renter plate, else device default."""
    booking = active_booking_for_device(device.id, at)
    if booking and booking.renter_plate:
        return booking.renter_plate
    return device.assigned_plate


def refresh_booking_statuses():
    """Promote approved bookings to active when their window starts; complete expired ones."""
    now = _utcnow()
    transitions: list[tuple] = []
    for booking in SpotBooking.query.filter(SpotBooking.status.in_(("approved", "active"))).all():
        starts = _aware(booking.starts_at)
        ends = _aware(booking.ends_at)
        old_status = booking.status
        if booking.status == "approved" and starts and starts <= now < (ends or now):
            booking.status = "active"
        elif ends and ends <= now:
            booking.status = "completed"
        if booking.status != old_status:
            transitions.append((booking.id, old_status, booking.status))
    db.session.commit()
    if transitions:
        try:
            import n8n_events

            for booking_id, _old, new_status in transitions:
                booking = SpotBooking.query.get(booking_id)
                if booking:
                    n8n_events.on_booking_event(booking, new_status)
                    if new_status == "completed" and booking.listing:
                        try:
                            import waitlist_service

                            waitlist_service.on_booking_completed(booking.listing.device_id)
                        except Exception:
                            pass
        except Exception:
            pass


def _charge_scheduled_remainder(booking: SpotBooking):
    owed = booking.total_spots - booking.paid_spots
    if owed <= 0:
        return
    transfer_spots(
        booking.renter,
        booking.listing.owner,
        owed,
        "booking_payment",
        "booking_payout",
        f"Scheduled parking remainder — booking #{booking.id}",
        booking.id,
    )
    booking.paid_spots += owed


def approve_booking(booking: SpotBooking) -> SpotBooking:
    listing = booking.listing
    owner = listing.owner
    renter = booking.renter
    now = _utcnow()

    if booking.booking_type == "instant":
        owed = booking.total_spots - booking.paid_spots
        if owed > 0:
            transfer_spots(
                renter,
                owner,
                owed,
                "booking_payment",
                "booking_payout",
                f"Instant parking — booking #{booking.id}",
                booking.id,
            )
            booking.paid_spots += owed
        starts = _aware(booking.starts_at)
        if starts and starts <= now:
            booking.status = "active"
        else:
            booking.status = "approved"
    else:
        if booking.paid_spots < booking.deposit_spots:
            raise ValueError("Deposit not recorded for this booking")
        _charge_scheduled_remainder(booking)
        starts = _aware(booking.starts_at)
        if starts and starts <= now:
            booking.status = "active"
        else:
            booking.status = "approved"

    return booking


def create_instant_booking(
    listing: SpotListing,
    renter: User,
    renter_plate: str,
    hours: int,
    starts_at: datetime | None = None,
    promo_code: str | None = None,
) -> SpotBooking:
    refresh_booking_statuses()
    if not listing.is_active:
        raise ValueError("This spot is not available for rent")
    if listing.owner_id == renter.id:
        raise ValueError("You cannot rent your own spot")

    starts_at = _aware(starts_at or _utcnow())
    ends_at = starts_at + timedelta(hours=max(config.MIN_INSTANT_HOURS, min(hours, config.MAX_BOOKING_HOURS)))
    total = calculate_instant_total(listing, hours)
    if promo_code:
        import promo_service

        total, _promo = promo_service.apply_booking_promo(listing.id, total, promo_code)

    overlap = (
        SpotBooking.query.filter(
            SpotBooking.listing_id == listing.id,
            SpotBooking.status.in_(("pending_approval", "approved", "active")),
            SpotBooking.starts_at < ends_at,
            SpotBooking.ends_at > starts_at,
        ).first()
    )
    if overlap:
        raise ValueError("This spot is already booked for part of that time")

    booking = SpotBooking(
        listing_id=listing.id,
        renter_id=renter.id,
        renter_plate=renter_plate,
        booking_type="instant",
        status="pending_approval",
        starts_at=starts_at,
        ends_at=ends_at,
        deposit_spots=0,
        total_spots=total,
        paid_spots=0,
    )
    db.session.add(booking)
    db.session.flush()

    if listing.approval_mode == "auto":
        if user_balance(renter) < total:
            raise ValueError(f"Insufficient {config.WALLET_CURRENCY_NAME.lower()} balance")
        approve_booking(booking)
    else:
        if user_balance(renter) < total:
            raise ValueError(
                f"Insufficient {config.WALLET_CURRENCY_NAME.lower()} balance — "
                "funds are checked again when the owner approves"
            )

    db.session.commit()
    return booking


def create_scheduled_booking(
    listing: SpotListing,
    renter: User,
    renter_plate: str,
    starts_at: datetime,
    ends_at: datetime,
    promo_code: str | None = None,
) -> SpotBooking:
    refresh_booking_statuses()
    if not listing.is_active:
        raise ValueError("This spot is not available for rent")
    if listing.owner_id == renter.id:
        raise ValueError("You cannot reserve your own spot")

    starts_at = _aware(starts_at)
    ends_at = _aware(ends_at)
    if ends_at <= starts_at:
        raise ValueError("End time must be after start time")
    if starts_at < _utcnow() - timedelta(minutes=5):
        raise ValueError("Cannot schedule in the past")

    total, deposit, _hours = calculate_scheduled_total(listing, starts_at, ends_at)
    if promo_code:
        import promo_service

        total, _promo = promo_service.apply_booking_promo(listing.id, total, promo_code)
        deposit = max(1, min(deposit, total))

    overlap = (
        SpotBooking.query.filter(
            SpotBooking.listing_id == listing.id,
            SpotBooking.status.in_(("pending_approval", "approved", "active")),
            SpotBooking.starts_at < ends_at,
            SpotBooking.ends_at > starts_at,
        ).first()
    )
    if overlap:
        raise ValueError("This spot is already reserved for part of that time")

    if user_balance(renter) < deposit:
        raise ValueError(f"Insufficient {config.WALLET_CURRENCY_NAME.lower()} for the scheduling deposit")

    booking = SpotBooking(
        listing_id=listing.id,
        renter_id=renter.id,
        renter_plate=renter_plate,
        booking_type="scheduled",
        status="pending_approval",
        starts_at=starts_at,
        ends_at=ends_at,
        deposit_spots=deposit,
        total_spots=total,
        paid_spots=0,
    )
    db.session.add(booking)
    db.session.flush()

    transfer_spots(
        renter,
        listing.owner,
        deposit,
        "booking_deposit",
        "booking_deposit_received",
        f"Scheduling deposit — booking #{booking.id}",
        booking.id,
    )
    booking.paid_spots = deposit

    if listing.approval_mode == "auto":
        approve_booking(booking)

    db.session.commit()
    return booking


def owner_approve_booking(booking: SpotBooking, owner: User) -> SpotBooking:
    if booking.listing.owner_id != owner.id:
        raise ValueError("Not your listing")
    if booking.status != "pending_approval":
        raise ValueError("Booking is not awaiting approval")

    owed = booking.total_spots - booking.paid_spots
    if owed > 0 and user_balance(booking.renter) < owed:
        raise ValueError(f"Renter has insufficient {config.WALLET_CURRENCY_NAME.lower()} to complete payment")

    approve_booking(booking)
    db.session.commit()
    return booking


def owner_reject_booking(booking: SpotBooking, owner: User) -> SpotBooking:
    if booking.listing.owner_id != owner.id:
        raise ValueError("Not your listing")
    if booking.status != "pending_approval":
        raise ValueError("Booking is not awaiting approval")

    if booking.paid_spots > 0:
        credit_spots(
            booking.renter,
            booking.paid_spots,
            "booking_refund",
            f"Refund — booking #{booking.id} rejected",
            booking.id,
        )
        debit_spots(
            booking.listing.owner,
            booking.paid_spots,
            "booking_refund",
            f"Refund issued — booking #{booking.id}",
            booking.id,
        )
    booking.status = "rejected"
    db.session.commit()
    return booking


def mock_topup(user: User, lei_amount: int) -> int:
    spots = lei_to_spots(lei_amount)
    if spots <= 0:
        raise ValueError("Enter a positive amount")
    credit_spots(user, spots, "topup", f"Top-up {lei_amount} lei ({spots} {config.WALLET_CURRENCY_NAME})")
    db.session.commit()
    return spots


def activate_subscription(user: User) -> None:
    """Charge monthly subscription (50 lei) and grant 50 Spots."""
    fee = config.SUBSCRIPTION_MONTHLY_LEI
    grant = spot_prices.credits_to_hundredths(config.SUBSCRIPTION_MONTHLY_SPOTS)
    spots_fee = lei_to_spots(fee)

    if user_balance(user) < spots_fee:
        raise ValueError(
            f"You need at least {config.SUBSCRIPTION_MONTHLY_LEI} {config.WALLET_CURRENCY_NAME.lower()} ({fee} lei) on your balance to activate subscription, "
            "or use the card checkout to pay in lei."
        )

    debit_spots(user, spots_fee, "subscription", f"Monthly subscription ({fee} lei)")
    credit_spots(
        user,
        grant,
        "subscription_grant",
        f"Monthly {config.WALLET_CURRENCY_NAME.lower()} grant ({config.SUBSCRIPTION_MONTHLY_SPOTS} {config.WALLET_CURRENCY_NAME})",
    )
    now = _utcnow()
    user.subscription_active = True
    if not user.subscription_started_at:
        user.subscription_started_at = now
    user.subscription_next_billing_at = now + timedelta(days=30)
    db.session.commit()


def subscribe_with_card_mock(user: User) -> None:
    """Mock card payment: pay 50 lei subscription and receive 50 Spots (no balance debit)."""
    grant = spot_prices.credits_to_hundredths(config.SUBSCRIPTION_MONTHLY_SPOTS)
    now = _utcnow()
    credit_spots(
        user,
        grant,
        "subscription_grant",
        f"Monthly subscription — {grant} {config.WALLET_CURRENCY_NAME} (mock card)",
    )
    user.subscription_active = True
    if not user.subscription_started_at:
        user.subscription_started_at = now
    user.subscription_next_billing_at = now + timedelta(days=30)
    db.session.commit()


def process_subscription_renewals():
    """Grant monthly Spots when subscription renews (mock: auto-renew if balance allows)."""
    now = _utcnow()
    for user in User.query.filter_by(subscription_active=True).all():
        next_bill = _aware(user.subscription_next_billing_at)
        if not next_bill or next_bill > now:
            continue
        fee = lei_to_spots(config.SUBSCRIPTION_MONTHLY_LEI)
        grant = spot_prices.credits_to_hundredths(config.SUBSCRIPTION_MONTHLY_SPOTS)
        try:
            debit_spots(user, fee, "subscription", "Monthly subscription renewal")
            credit_spots(user, grant, "subscription_grant", f"Monthly {config.WALLET_CURRENCY_NAME.lower()} grant")
            user.subscription_next_billing_at = now + timedelta(days=30)
        except ValueError:
            user.subscription_active = False
    db.session.commit()


def ensure_user_wallet(user: User):
    """Run subscription renewal check when user opens wallet pages."""
    if user.id and user.id > 0:
        process_subscription_renewals()


def request_bank_withdrawal(
    user: User,
    *,
    account_holder: str,
    iban: str,
    bank_name: str | None = None,
) -> "WalletWithdrawal":
    from models import WalletWithdrawal
    import receipt_pdf

    amount = spot_prices.credits_to_hundredths(config.WITHDRAWAL_CREDITS)
    if user_balance(user) < amount:
        raise ValueError(
            f"You need at least {config.WITHDRAWAL_CREDITS} {config.WALLET_CURRENCY_NAME.lower()} to withdraw "
            f"({config.WITHDRAWAL_LEI} lei)."
        )
    iban_clean = "".join(ch for ch in (iban or "").upper() if ch.isalnum())
    if len(iban_clean) < 15:
        raise ValueError("Enter a valid IBAN.")
    holder = (account_holder or "").strip()
    if len(holder) < 2:
        raise ValueError("Enter the account holder name.")

    user.payout_account_holder = holder
    user.payout_iban = iban_clean
    user.payout_bank_name = (bank_name or "").strip() or None

    token = receipt_pdf.new_receipt_token()
    debit_spots(
        user,
        amount,
        "withdrawal",
        f"Bank withdrawal — {config.WITHDRAWAL_LEI} lei (pending)",
    )
    tx = (
        SpotTransaction.query.filter_by(user_id=user.id, kind="withdrawal")
        .order_by(SpotTransaction.created_at.desc())
        .first()
    )
    if tx:
        tx.receipt_token = token

    withdrawal = WalletWithdrawal(
        user_id=user.id,
        credits_amount=amount,
        lei_amount=config.WITHDRAWAL_LEI,
        account_holder=holder,
        iban=iban_clean,
        bank_name=user.payout_bank_name,
        status="pending",
        receipt_token=token,
    )
    db.session.add(withdrawal)
    db.session.commit()

    receipt_pdf.save_receipt(
        token,
        "Withdrawal request",
        [
            ("Amount", f"{amount} {config.WALLET_CURRENCY_NAME} → {config.WITHDRAWAL_LEI} lei"),
            ("Status", "Pending bank transfer"),
            ("Account holder", holder),
            ("IBAN", iban_clean),
            ("Bank", user.payout_bank_name or "—"),
        ],
    )
    return withdrawal


def attach_receipt_to_last_transaction(user: User, kind: str, title: str, lines: list[tuple[str, str]]) -> str:
    import receipt_pdf

    token = receipt_pdf.new_receipt_token()
    tx = (
        SpotTransaction.query.filter_by(user_id=user.id, kind=kind)
        .order_by(SpotTransaction.created_at.desc())
        .first()
    )
    if tx:
        tx.receipt_token = token
        db.session.commit()
    receipt_pdf.save_receipt(token, title, lines)
    return token

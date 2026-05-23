"""Fractional Credits prices stored as hundredths (100 = 1.00 Credit).

Legacy rows may still hold tenths (10 = 1.0); helpers normalize on read.
Billing debits round up to whole Credits: ceil(hundredths / 100).
"""

from __future__ import annotations

import math

from models import SpotListing


def _normalize_hundredths(raw: int | None, legacy_per_hour: int | None = None) -> int:
    if raw is not None and int(raw) >= 1000:
        return int(raw)
    if raw is not None and int(raw) > 0:
        return int(raw) * 10
    if legacy_per_hour:
        return int(legacy_per_hour) * 100
    return 1000


def format_hundredths(hundredths: int | None) -> str:
    if hundredths is None:
        return "—"
    hundredths = int(hundredths)
    whole, frac = divmod(hundredths, 100)
    if frac == 0:
        return str(whole)
    return f"{whole}.{frac:02d}"


def format_tenths(tenths: int | None) -> str:
    """Backward-compatible alias; values are hundredths."""
    return format_hundredths(tenths)


def parse_decimal_to_hundredths(value: str | float | int | None, default_hundredths: int) -> int:
    if value is None or value == "":
        return default_hundredths
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default_hundredths
    return max(100, int(round(f * 100)))


def parse_decimal_to_tenths(value: str | float | int | None, default_tenths: int) -> int:
    return parse_decimal_to_hundredths(value, default_tenths)


def legacy_instant_hundredths(listing: SpotListing) -> int:
    return _normalize_hundredths(
        listing.instant_price_tenths,
        listing.instant_price_per_hour,
    )


def legacy_schedule_hundredths(listing: SpotListing) -> int:
    return _normalize_hundredths(
        listing.schedule_price_tenths,
        listing.schedule_price_per_hour,
    )


# Backward-compatible aliases (pricing_engine and older call sites)
legacy_instant_tenths = legacy_instant_hundredths
legacy_schedule_tenths = legacy_schedule_hundredths


def legacy_deposit_hundredths(listing: SpotListing) -> int:
    if listing.schedule_deposit_tenths:
        return _normalize_hundredths(listing.schedule_deposit_tenths, listing.schedule_deposit_spots)
    return int(listing.schedule_deposit_spots or 5) * 100


def effective_instant_hundredths(listing: SpotListing) -> int:
    if listing.pricing_mode == "auto" and listing.dynamic_instant_tenths:
        return _normalize_hundredths(listing.dynamic_instant_tenths, listing.instant_price_per_hour)
    return legacy_instant_hundredths(listing)


def effective_schedule_hundredths(listing: SpotListing) -> int:
    if listing.pricing_mode == "auto" and listing.dynamic_schedule_tenths:
        return _normalize_hundredths(listing.dynamic_schedule_tenths, listing.schedule_price_per_hour)
    return legacy_schedule_hundredths(listing)


def effective_deposit_hundredths(listing: SpotListing) -> int:
    return legacy_deposit_hundredths(listing)


def hundredths_to_billable_spots(total_hundredths: int) -> int:
    """Round up fractional Credits for wallet debits."""
    return (int(total_hundredths) + 99) // 100


def tenths_to_billable_spots(total_tenths: int) -> int:
    return hundredths_to_billable_spots(total_tenths)


def instant_total_billable(listing: SpotListing, hours: int) -> int:
    return hundredths_to_billable_spots(effective_instant_hundredths(listing) * hours)


def schedule_total_billable(listing: SpotListing, hours: int) -> tuple[int, int]:
    total_hundredths = effective_schedule_hundredths(listing) * hours
    deposit_hundredths = min(effective_deposit_hundredths(listing), total_hundredths)
    return (
        hundredths_to_billable_spots(total_hundredths),
        hundredths_to_billable_spots(deposit_hundredths),
    )


# Aliases used by pricing_engine and legacy imports
legacy_instant_tenths = legacy_instant_hundredths
legacy_schedule_tenths = legacy_schedule_hundredths
legacy_deposit_tenths = legacy_deposit_hundredths
effective_instant_tenths = effective_instant_hundredths
effective_schedule_tenths = effective_schedule_hundredths
effective_deposit_tenths = effective_deposit_hundredths

"""Fractional Spots prices stored as tenths (10 = 1.0 Spot)."""

from __future__ import annotations

import math

from models import SpotListing


def format_tenths(tenths: int | None) -> str:
    if tenths is None:
        return "—"
    tenths = int(tenths)
    whole, frac = divmod(tenths, 10)
    if frac == 0:
        return str(whole)
    return f"{whole}.{frac}"


def parse_decimal_to_tenths(value: str | float | int | None, default_tenths: int) -> int:
    if value is None or value == "":
        return default_tenths
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default_tenths
    return max(10, int(round(f * 10)))


def legacy_instant_tenths(listing: SpotListing) -> int:
    if listing.instant_price_tenths:
        return int(listing.instant_price_tenths)
    return int(listing.instant_price_per_hour or 10) * 10


def legacy_schedule_tenths(listing: SpotListing) -> int:
    if listing.schedule_price_tenths:
        return int(listing.schedule_price_tenths)
    return int(listing.schedule_price_per_hour or 8) * 10


def legacy_deposit_tenths(listing: SpotListing) -> int:
    if listing.schedule_deposit_tenths:
        return int(listing.schedule_deposit_tenths)
    return int(listing.schedule_deposit_spots or 5) * 10


def effective_instant_tenths(listing: SpotListing) -> int:
    if listing.pricing_mode == "auto" and listing.dynamic_instant_tenths:
        return int(listing.dynamic_instant_tenths)
    return legacy_instant_tenths(listing)


def effective_schedule_tenths(listing: SpotListing) -> int:
    if listing.pricing_mode == "auto" and listing.dynamic_schedule_tenths:
        return int(listing.dynamic_schedule_tenths)
    return legacy_schedule_tenths(listing)


def effective_deposit_tenths(listing: SpotListing) -> int:
    return legacy_deposit_tenths(listing)


def tenths_to_billable_spots(total_tenths: int) -> int:
    """Round up fractional Spots for wallet debits."""
    return (int(total_tenths) + 9) // 10


def instant_total_billable(listing: SpotListing, hours: int) -> int:
    return tenths_to_billable_spots(effective_instant_tenths(listing) * hours)


def schedule_total_billable(listing: SpotListing, hours: int) -> tuple[int, int]:
    total_tenths = effective_schedule_tenths(listing) * hours
    deposit_tenths = min(effective_deposit_tenths(listing), total_tenths)
    return tenths_to_billable_spots(total_tenths), tenths_to_billable_spots(deposit_tenths)

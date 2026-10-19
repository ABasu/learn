"""Numeric display conventions for exchange-aware reports."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


INDIAN_LAKH = Decimal("100000")
INDIAN_CRORE = Decimal("10000000")
MILLION = Decimal("1000000")
BILLION = Decimal("1000000000")


def format_currency(
    value: int | float | Decimal,
    currency: str,
    convention: str,
    *,
    decimals: int = 1,
) -> str:
    """Format a raw currency amount according to its report's market convention.

    Indian reports use rupees, lakhs, and crores. Other markets use the
    international million/billion convention. ``value`` is always a raw amount
    in the given currency, never an already-scaled figure.
    """
    amount = Decimal(str(value))
    if convention == "indian":
        return _format_indian(amount, currency, decimals)
    if convention == "international":
        return _format_international(amount, currency, decimals)
    raise ValueError(f"Unknown numeric convention: {convention}")


def _format_indian(amount: Decimal, currency: str, decimals: int) -> str:
    symbol = "₹" if currency.upper() == "INR" else f"{currency.upper()} "
    sign = "-" if amount < 0 else ""
    magnitude = abs(amount)

    if magnitude >= INDIAN_CRORE:
        return f"{sign}{symbol}{_scaled(magnitude, INDIAN_CRORE, decimals)} crore"
    if magnitude >= INDIAN_LAKH:
        return f"{sign}{symbol}{_scaled(magnitude, INDIAN_LAKH, decimals)} lakh"
    return f"{sign}{symbol}{_indian_grouping(magnitude)}"


def _format_international(amount: Decimal, currency: str, decimals: int) -> str:
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency.upper(), f"{currency.upper()} ")
    sign = "-" if amount < 0 else ""
    magnitude = abs(amount)

    if magnitude >= BILLION:
        return f"{sign}{symbol}{_scaled(magnitude, BILLION, decimals)} billion"
    if magnitude >= MILLION:
        return f"{sign}{symbol}{_scaled(magnitude, MILLION, decimals)} million"
    return f"{sign}{symbol}{magnitude.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,}"


def _scaled(value: Decimal, divisor: Decimal, decimals: int) -> str:
    precision = Decimal("1").scaleb(-decimals)
    number = (value / divisor).quantize(precision, rounding=ROUND_HALF_UP)
    return f"{number:,.{decimals}f}".rstrip("0").rstrip(".")


def _indian_grouping(value: Decimal) -> str:
    """Render amounts below one lakh with Indian comma grouping."""
    whole = f"{value.quantize(Decimal('1'), rounding=ROUND_HALF_UP):.0f}"
    if len(whole) <= 3:
        return whole
    tail, head = whole[-3:], whole[:-3]
    groups: list[str] = []
    while head:
        groups.append(head[-2:])
        head = head[:-2]
    return ",".join(reversed(groups)) + "," + tail

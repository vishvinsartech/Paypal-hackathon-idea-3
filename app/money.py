"""Money helpers. Always Decimal, never float. Stored in JSON as strings."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
SYMBOLS = {"USD": "$"}


def to_decimal(value: Decimal | str | int) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Use str or Decimal for money, never float")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def q(value: Decimal | str | int) -> Decimal:
    """Round to cents, half-up."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value: Decimal | str | int, currency: str = "USD") -> str:
    amount = f"{q(value):,.2f}"
    symbol = SYMBOLS.get(currency)
    return f"{symbol}{amount}" if symbol else f"{amount} {currency}"

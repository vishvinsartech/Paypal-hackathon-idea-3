"""Money maths from PayPal billing cycles (code, never the LLM). Decimal only."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.models import BillingCycleDef

CHARGES_PER_YEAR = {"DAY": 365, "WEEK": 52, "MONTH": 12, "YEAR": 1}


def year_one_cost(cycles: Sequence[BillingCycleDef]) -> Decimal:
    """Cost of the first year of PAID billing (free trial cycles skipped).
    Penwright: 3 x 24.99 + 9 x 49.99 = 524.88; add-on 12 x 9.99 = 119.88; Framewise at $19: 228.00."""
    paid = [c for c in cycles if c.price > 0]
    if not paid:
        return Decimal("0.00")
    unit = paid[0]
    remaining = max(1, CHARGES_PER_YEAR[unit.interval_unit] // max(1, unit.interval_count))
    total = Decimal("0")
    for cycle in paid:
        count = remaining if cycle.total_cycles == 0 else min(cycle.total_cycles, remaining)
        total += cycle.price * count
        remaining -= count
        if remaining <= 0:
            break
    return total.quantize(Decimal("0.01"))


def paid_prices(cycles: Sequence[BillingCycleDef]) -> list[Decimal]:
    """Distinct paid prices in billing order."""
    out: list[Decimal] = []
    for c in cycles:
        if c.price > 0 and c.price not in out:
            out.append(c.price)
    return out

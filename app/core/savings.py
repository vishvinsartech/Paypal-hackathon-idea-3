"""Money maths from PayPal billing cycles (code, never the LLM). Decimal only."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.models import BillingCycleDef, Subscription

CHARGES_PER_YEAR = {"DAY": 365, "WEEK": 52, "MONTH": 12, "YEAR": 1}


def year_one_cost(cycles: Sequence[BillingCycleDef]) -> Decimal:
    """Cost of the first year of PAID billing (free trial cycles skipped).
    Penwright: 3 x 24.99 + 9 x 49.99 = 524.88 (the "Money protected" KPI)."""
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


def protected_by_currency(subs: Sequence[Subscription], user_id: str) -> dict[str, Decimal]:
    """Year-one cost avoided by cancels SubGuard made (user-confirmed or timer), per currency.
    Corner case 8: amounts in different currencies are never added together."""
    out: dict[str, Decimal] = {}
    for s in subs:
        if s.owner_id == user_id and s.protected_year_usd is not None and s.cancelled_by in ("user", "timer"):
            cur = s.consent_snapshot.currency if s.consent_snapshot else "USD"
            out[cur] = out.get(cur, Decimal("0.00")) + s.protected_year_usd
    return out


def money_protected(subs: Sequence[Subscription], user_id: str, currency: str = "USD") -> Decimal:
    """"Money protected" KPI in one currency (the demo currency); other currencies are reported separately."""
    return protected_by_currency(subs, user_id).get(currency, Decimal("0.00"))

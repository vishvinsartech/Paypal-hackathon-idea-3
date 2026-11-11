"""U14: the companion's verdict, in plain words, from the PayPal plan (code, never the LLM).

    "$0 today, then $24.99/month from Nov 22"
    "Rises to $49.99 after 3 months · up to $524.88 in year one"
    PayPal check: "The page says $0 today. The PayPal plan charges $24.99 on Nov 22."
    3 things to know: the top findings by severity, one line each (D-150).

The same cost wording is used on Priya's subscription card (U7), from the consent snapshot's cycles.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from app.core.savings import year_one_cost
from app.integrations.paypal_types import first_paid_price
from app.models import BillingCycleDef
from app.review_types import TYPE_LABELS, Clause, PayPalCheckRow

UNIT = {"DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}
# Shown elsewhere in the companion, so not repeated in "3 things to know": the injection note (U18) and the
# PayPal check box (TERMS_MISMATCH). Clear terms are good news, not a thing to watch.
NOT_A_THING = {"PROMPT_INJECTION_ATTEMPT", "TERMS_MISMATCH", "CLEAR_TERMS"}
# Tie-break for equal severity: what the verdict line doesn't already say comes first.
TIE = ["NOTICE_PERIOD", "HARD_CANCEL", "EARLY_TRIAL_TERMINATION", "PRECHECKED_ADDON", "AUTO_RENEW",
       "INTRO_PRICE_STEP_UP", "HIDDEN_TEXT_STYLE"]

Money = Callable[[Decimal], str]


def _paid(cycles: Sequence[BillingCycleDef]) -> list[BillingCycleDef]:
    return [c for c in cycles if c.price > 0]


def cost_line(cycles: Sequence[BillingCycleDef], money: Money, first_charge: str | None) -> str:
    """ "$0 today, then $24.99/month from Nov 22" (trial) or "$9.99/month from today" (no trial)."""
    paid = _paid(cycles)
    if not paid:
        return f"{money(Decimal('0'))} today, no paid plan"
    per = UNIT[paid[0].interval_unit]
    price = f"{money(first_paid_price(cycles))}/{per}"
    if cycles and cycles[0].price == 0:
        return f"{money(Decimal('0'))} today, then {price}" + (f" from {first_charge}" if first_charge else "")
    return f"{price} from today"


def step_up_text(cycles: Sequence[BillingCycleDef], money: Money) -> str | None:
    """ "Rises to $49.99 after 3 months" when the paid price steps up after a fixed number of cycles."""
    paid = _paid(cycles)
    if len(paid) < 2 or paid[0].total_cycles == 0 or paid[1].price == paid[0].price:
        return None
    n, unit = paid[0].total_cycles, UNIT[paid[0].interval_unit]
    return f"Rises to {money(paid[1].price)} after {n} {unit}{'s' if n != 1 else ''}"


def sub_line(cycles: Sequence[BillingCycleDef], money: Money) -> str:
    parts = [p for p in (step_up_text(cycles, money), f"up to {money(year_one_cost(cycles))} in year one") if p]
    return " · ".join(parts)


def paypal_line(cycles: Sequence[BillingCycleDef], money: Money, first_charge: str | None,
                rows: Sequence[PayPalCheckRow]) -> tuple[str, bool]:
    """The PayPal check box: what the page leads with vs what PayPal will charge. (text, is_warning)."""
    amount = money(first_paid_price(cycles))
    mismatch = any(not r.match for r in rows)
    if cycles and cycles[0].price == 0:
        when = f" on {first_charge}" if first_charge else " after the trial"
        lead = f"The page says {money(Decimal('0'))} today. " if mismatch else ""
        return f"{lead}The PayPal plan charges {amount}{when}.", mismatch
    return f"The PayPal plan charges {amount} today" + (", as the page says." if not mismatch else "."), mismatch


def top_things(clauses: Sequence[Clause], n: int = 3) -> list[dict[str, Any]]:
    """The top `n` findings by severity, one per type, as one line each (plain label + plain English)."""
    seen: set[str] = set()
    picked: list[Clause] = []
    order = {t: i for i, t in enumerate(TIE)}
    for c in sorted(clauses, key=lambda c: (-c.severity, order.get(c.type, 99))):
        if c.type in NOT_A_THING or c.type in seen:
            continue
        seen.add(c.type)
        picked.append(c)
    return [{"type": c.type, "label": TYPE_LABELS.get(c.type, c.type), "text": c.plain_english,
             "severity": c.severity} for c in picked[:n]]


def evidence_quotes(clauses: Sequence[Clause]) -> list[dict[str, Any]]:
    """U15: every quoted clause once (duplicate quotes dropped), plain English first, the type as a chip."""
    seen: set[str] = set()
    out = []
    for c in sorted(clauses, key=lambda c: -c.severity):
        key = " ".join(c.quote.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": c.type, "label": TYPE_LABELS.get(c.type, c.type), "text": c.plain_english,
                    "quote": c.quote, "severity": c.severity})
    return out


def rows_failing_first(rows: Sequence[PayPalCheckRow]) -> list[dict[str, Any]]:
    """U16: the cross-check with the failing rows first, each with its plain label."""
    return [{**r.model_dump(mode="json"), "label": r.label or f"{r.item}: {r.page_says}"}
            for r in sorted(rows, key=lambda r: r.match)]


def verdict(cycles: Sequence[BillingCycleDef], money: Money, first_charge: str | None, clauses: Sequence[Clause],
            rows: Sequence[PayPalCheckRow]) -> dict[str, Any]:
    text, warn = paypal_line(cycles, money, first_charge, rows)
    quotes = evidence_quotes(clauses)
    return {"line": cost_line(cycles, money, first_charge), "sub": sub_line(cycles, money),
            "paypal_line": text, "paypal_warn": warn, "things": top_things(clauses),
            "quotes": quotes, "rows": rows_failing_first(rows),
            "evidence_label": f"{len(quotes)} quoted clause{'s' if len(quotes) != 1 else ''}, cross-check table"}

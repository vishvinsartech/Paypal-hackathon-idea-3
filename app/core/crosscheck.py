"""PayPal cross-check (spec 7.2 step 4): page claims vs the real PayPal plan. PayPal wins for all money maths.

A difference -> one TERMS_MISMATCH clause (quoting the page's most prominent text) plus a row per check.
Checks: first charge day and amount (as the reviewer read them), every PayPal price is stated on the page,
and the prominent checkout text shows a price PayPal will actually charge (not just "$0 today").
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.core.savings import paid_prices
from app.integrations.capture import PageCapture, TextBlock, normalize_ws
from app.integrations.paypal_types import PlanView, first_charge_day, first_paid_price
from app.pricing import SYMBOLS
from app.review_types import Clause, PayPalCheckRow, ReviewResult

PROMINENT_MIN_PX = 18.0


def after_start(offset: int) -> str:
    """Relative to sign-up, never a sim day (B2)."""
    return "the day you start" if offset == 0 else f"{offset} day{'s' if offset != 1 else ''} after you start"


def money_str(amount: Decimal, currency: str) -> str:
    text = f"{amount:,.0f}" if amount == amount.to_integral_value() else f"{amount:,.2f}"
    sym = SYMBOLS.get(currency)
    return f"{sym}{text}" if sym else f"{text} {currency}"


def price_regex(amount: Decimal, currency: str) -> re.Pattern[str]:
    whole = amount == amount.to_integral_value()
    num = re.escape(f"{amount:,.0f}") + r"(\.00)?" if whole else re.escape(f"{amount:,.2f}")
    sym = re.escape(SYMBOLS.get(currency, currency))
    return re.compile(rf"(?:{sym}\s?{num}|{num}\s?{re.escape(currency)})(?![\d])")


def prominent_blocks(capture: PageCapture) -> list[TextBlock]:
    """Big, visible, readable text on the checkout page itself (headline, price box)."""
    blocks = [b for b in capture.main_blocks() if not b.hidden and b.font_px >= PROMINENT_MIN_PX and b.contrast >= 3
              and b.testid != "shop-banner"]
    return sorted(blocks, key=lambda b: -b.font_px)


def cross_check(capture: PageCapture, plan: PlanView,
                review: ReviewResult) -> tuple[list[PayPalCheckRow], Clause | None]:
    cur = plan.currency
    rows: list[PayPalCheckRow] = []
    problems: list[str] = []
    no_trial = bool(plan.billing_cycles) and plan.billing_cycles[0].price > 0
    pp_day = 0 if no_trial else first_charge_day(plan.billing_cycles, 0)  # no trial: charged at signup
    pp_amount = first_paid_price(plan.billing_cycles)

    if review.first_charge_day is not None:
        ok = review.first_charge_day == pp_day
        rows.append(PayPalCheckRow(item="First charge", page_says=after_start(review.first_charge_day),
                                   paypal_says=after_start(pp_day), match=ok,
                                   label=f"First charge {after_start(pp_day)}" + ("" if ok else
                                         f", but the page implies {after_start(review.first_charge_day)}")))
        if not ok:
            problems.append(f"the page implies the first charge {after_start(review.first_charge_day)}, "
                            f"PayPal bills {after_start(pp_day)}")
    if review.first_charge_amount is not None:
        ok = review.first_charge_amount == pp_amount
        rows.append(PayPalCheckRow(item="First charge amount", page_says=money_str(review.first_charge_amount, cur),
                                   paypal_says=money_str(pp_amount, cur), match=ok,
                                   label=f"First charge of {money_str(pp_amount, cur)}" + (" matches the page" if ok
                                         else f", but the page says {money_str(review.first_charge_amount, cur)}")))
        if not ok:
            problems.append(f"the page says {money_str(review.first_charge_amount, cur)}, PayPal will charge "
                            f"{money_str(pp_amount, cur)}")

    full = normalize_ws(capture.full_text)
    prominent = prominent_blocks(capture)
    prominent_text = " ".join(b.text for b in prominent)
    for price in paid_prices(plan.billing_cycles):
        rx = price_regex(price, cur)
        stated, upfront = bool(rx.search(full)), bool(rx.search(prominent_text))
        where = "headline / price box" if upfront else ("fine print or terms only" if stated else "not on the page")
        plain = "shown up front" if upfront else ("shown only in fine print" if stated else "not on the page")
        rows.append(PayPalCheckRow(item=f"PayPal price {money_str(price, cur)}", page_says=where,
                                   paypal_says=f"{money_str(price, cur)} per cycle", match=stated,
                                   label=f"Price {money_str(price, cur)} {plain}"))
        if not stated:
            problems.append(f"PayPal charges {money_str(price, cur)}, which the page never states")
    paid = paid_prices(plan.billing_cycles)
    upfront_ok = not paid or any(price_regex(p, cur).search(prominent_text) for p in paid)
    if paid:
        headline = prominent[0].text if prominent else "(nothing prominent)"
        charged = " then ".join(money_str(p, cur) for p in paid)
        rows.append(PayPalCheckRow(item="Headline price", page_says=headline, paypal_says=charged, match=upfront_ok,
                                   label="The headline shows a price PayPal charges" if upfront_ok else
                                   f"The headline says “{headline}”, but PayPal charges {charged}"))
    if not upfront_ok:
        later = " then ".join(money_str(p, cur) for p in paid)
        problems.append(f"the headline doesn't show any price PayPal will charge; the PayPal plan bills {later}")

    if not problems or not prominent and not capture.main_blocks():
        return rows, None
    evidence = (prominent or capture.main_blocks())[0]
    clause = Clause(
        type="TERMS_MISMATCH", quote=evidence.text, severity=4, evidence_testid=evidence.testid,
        source="paypal_check",
        plain_english="The PayPal plan doesn't match what the page shows up front: " + "; ".join(problems) + ".",
    )
    return rows, clause

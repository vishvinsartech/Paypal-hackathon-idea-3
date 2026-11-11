"""Numbers behind the AG Charts graphs on Priya's dashboard (D-108). Money comes from PayPal billing cycles in code
(Decimal, sent as strings; the browser only plots them). Risk from the stored review, usage from usage.json."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.core import timers as tm
from app.core.savings import CHARGES_PER_YEAR
from app.core.services import Services
from app.models import BillingCycleDef, Subscription
from app.pricing import SYMBOLS

RISK_LABELS = {"money_factor": "Money at stake", "library_bonus": "Known dark pattern"}


def first_year_charges(cycles: Sequence[BillingCycleDef]) -> list[Decimal]:
    """Each paid charge in the first paid year, in order (sums to savings.year_one_cost)."""
    paid = [c for c in cycles if c.price > 0]
    if not paid:
        return []
    remaining = max(1, CHARGES_PER_YEAR[paid[0].interval_unit] // max(1, paid[0].interval_count))
    out: list[Decimal] = []
    for c in paid:
        n = remaining if c.total_cycles == 0 else min(c.total_cycles, remaining)
        out += [c.price] * n
        remaining -= n
        if remaining <= 0:
            break
    return out


def cost_curve(svc: Services, subs: list[Subscription]) -> dict[str, Any]:
    """Cumulative first-year cost if kept vs what the user actually pays (0 once SubGuard cancelled it)."""
    series = []
    for s in subs:
        if s.consent_snapshot is None:
            continue
        charges = first_year_charges(s.consent_snapshot.billing_cycles)
        stopped = s.status == "CANCELLED" and s.cancelled_by in ("user", "timer")
        series.append({"label": svc.merchant(s.merchant_id).name, "stopped": stopped, "charges": charges})
    preview = not series
    if preview:  # nothing signed up yet: show what the Penwright plan would cost
        for m in svc.store.load("merchants").items:
            for p in m.plans:
                series.append({"label": f"{m.name} ({p.name})", "stopped": False,
                               "charges": first_year_charges(p.billing_cycles)})
    months = max((len(x["charges"]) for x in series), default=0)
    rows, kept, pays = [], Decimal("0"), Decimal("0")
    for i in range(months):
        month = sum((x["charges"][i] for x in series if i < len(x["charges"])), start=Decimal("0"))
        kept += month
        pays += sum((x["charges"][i] for x in series if i < len(x["charges"]) and not x["stopped"]),
                    start=Decimal("0"))
        rows.append({"month": f"M{i + 1}", "charge": str(month), "if_kept": str(kept), "you_pay": str(pays)})
    return {"rows": rows, "preview": preview, "labels": [x["label"] for x in series],
            "symbol": SYMBOLS.get(svc.settings.pricing.demo_currency, ""),
            "if_kept_text": svc.money(kept), "you_pay_text": svc.money(pays),
            "protected_text": svc.money(kept - pays)}


def risk_breakdown(svc: Services, subs: list[Subscription]) -> dict[str, Any] | None:
    reviews = [r for s in subs if (r := tm.review_for(svc, s)) is not None]
    if not reviews:
        reviews = sorted(svc.store.load("reviews").items, key=lambda r: r.created_at)[-1:]
    if not reviews:
        return None
    r = reviews[-1]
    risk = r.data.risk
    parts = [{"label": k.replace("_", " ").title(), "points": v, "group": "Fine print"}
             for k, v in risk.type_points.items() if v]
    parts += [{"label": k.replace("_", " ").title(), "points": v, "group": "Hidden styling"}
              for k, v in risk.style_points.items() if v]
    if risk.money_factor:
        parts.append({"label": RISK_LABELS["money_factor"], "points": float(risk.money_factor), "group": "Money"})
    if risk.library_bonus:
        parts.append({"label": RISK_LABELS["library_bonus"], "points": risk.library_bonus, "group": "Library"})
    parts.sort(key=lambda p: -p["points"])
    return {"merchant": svc.merchant(r.merchant_id).name, "score": r.risk_score, "parts": parts}


def usage(svc: Services, user_id: str, subs: list[Subscription]) -> dict[str, Any]:
    opens = Counter(u.day for u in svc.store.load("usage").items if u.user_id == user_id and u.kind == "open")
    first = next((s for s in subs if s.next_billing_day is not None), None)
    end = max([svc.day, first.next_billing_day if first and first.next_billing_day else 0, *opens])
    deadline = None
    if first and (review := tm.review_for(svc, first)) is not None:
        deadline = review.data.deadlines.real_cancel_deadline_day
    return {"rows": [{"day": f"Day {d}", "opens": opens[d]} for d in range(0, end + 1)],
            "total": sum(opens.values()), "deadline_day": deadline,
            "first_charge_day": first.next_billing_day if first else None}


def analytics(svc: Services, user_id: str) -> dict[str, Any]:
    subs = [s for s in svc.store.load("subscriptions").items
            if s.owner_id == user_id and s.status != "APPROVAL_PENDING"]
    return {"today": svc.day, "cost": cost_curve(svc, subs), "risk": risk_breakdown(svc, subs),
            "usage": usage(svc, user_id, subs)}

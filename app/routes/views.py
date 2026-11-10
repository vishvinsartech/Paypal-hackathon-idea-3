"""Read-only view models for the dashboard (one call per panel, so the JS does no maths)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core import timers as tm
from app.core.services import Services
from app.core.usage import last_open_day
from app.integrations.paypal_types import cycle_days
from app.models import BillingCycleDef, Subscription, Timer
from app.routes.actions import get_services

router = APIRouter(prefix="/api/view")


def step_up(cycles: list[BillingCycleDef], signup_day: int) -> tuple[int | None, int | None]:
    """(trial_end_day, step_up_day) from the agreed billing cycles; None when not applicable."""
    day, trial_end, first_price = signup_day, None, None
    for c in cycles:
        if c.tenure_type == "TRIAL" and c.price == 0:
            day += cycle_days(c) * max(1, c.total_cycles)
            trial_end = day
            continue
        if first_price is None:
            first_price = c.price
        elif c.price != first_price:
            return trial_end, day + 1 if trial_end is not None else day
        if c.total_cycles == 0:
            break
        day += cycle_days(c) * c.total_cycles
    return trial_end, None


def current_timer(timers: list[Timer], sub_id: str) -> Timer | None:
    mine = [t for t in timers if t.subscription_id == sub_id]
    return next((t for t in mine if t.status == "PENDING"), mine[-1] if mine else None)


def sub_view(svc: Services, sub: Subscription, timers: list[Timer]) -> dict[str, Any]:
    merchant = svc.merchant(sub.merchant_id)
    plan = next((p for p in merchant.plans if p.key == sub.plan_key), None)
    snap = sub.consent_snapshot
    review = tm.review_for(svc, sub)
    timer = current_timer(timers, sub.id)
    trial_end, step_day = step_up(snap.billing_cycles, sub.signup_day) if snap else (None, None)
    prices = [c.price for c in snap.billing_cycles if c.price > 0] if snap else []
    timer_text = None
    if timer and timer.status == "PENDING":
        timer_text = f"Check-in Day {timer.reminder_day} · cancel Day {timer.fire_day} unless you keep it"
    elif timer:
        timer_text = {"KEPT": "Kept", "FIRED": f"Fired Day {timer.fire_day}", "FAILED": "Failed: needs you",
                      "CANCELLED": "Not needed"}[timer.status]
    return {
        "id": sub.id, "paypal_id": sub.paypal_id, "merchant_id": merchant.id, "merchant": merchant.name,
        "plan": plan.name if plan else sub.plan_key, "plan_key": sub.plan_key,
        "status": sub.status, "essential": sub.essential, "fair_trial": merchant.fair_trial_member,
        "signup_day": sub.signup_day, "next_billing_day": sub.next_billing_day,
        "price_text": f"{svc.money(snap.price)}/{_per(snap.billing_cycles)}" if snap else "",
        "next_charge_text": (f"Day {sub.next_billing_day} · {svc.money(prices[0])}"
                             if sub.next_billing_day is not None and prices and sub.status == "ACTIVE" else "—"),
        "risk": review.risk_score if review else None, "review_id": review.id if review else None,
        "last_used_day": last_open_day(svc.store, sub.owner_id, sub.merchant_id, svc.day),
        "trial_end_day": trial_end, "step_up_day": step_day,
        "step_up_text": f"{svc.money(prices[-1])}" if step_day is not None and prices else None,
        "deadline_day": timer.deadline_day if timer and timer.kind == "trial" else None,
        "timer": None if timer is None else {"fire_day": timer.fire_day, "status": timer.status,
                                             "kind": timer.kind, "layer2": timer.layer2},
        "timer_text": timer_text, "kept_day": sub.kept_day,
        "cancelled_day": sub.cancelled_day, "cancelled_by": sub.cancelled_by,
    }


def _per(cycles: list[BillingCycleDef]) -> str:
    paid = next((c for c in cycles if c.price > 0), None)
    return {"DAY": "day", "WEEK": "wk", "MONTH": "mo", "YEAR": "yr"}[paid.interval_unit] if paid else "mo"


@router.get("/subscriptions")
def subscriptions(user: str = "usera", svc: Services = Depends(get_services)) -> dict[str, Any]:
    timers = svc.store.load("timers").items
    subs = [s for s in svc.store.load("subscriptions").items if s.owner_id == user and s.status != "APPROVAL_PENDING"]
    return {"today": svc.day, "rows": [sub_view(svc, s, timers) for s in subs]}

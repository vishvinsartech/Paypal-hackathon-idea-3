"""Demo controls (spec 7.4): reset (+ demo seed), advance the sim clock, Framewise price rise, toggle Fair Trial."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from app.clock import advance as clock_advance
from app.core.auditor import save_review
from app.core.demo_seed import ReviewFn, seed_demo
from app.core.escalation import watch_prices
from app.core.risk import compute_deadlines
from app.core.services import Services
from app.integrations.paypal_gateway import Ctx
from app.routes.actions import get_services

router = APIRouter(prefix="/api/demo")
PRICE_RISE_PLAN = "framewise-basic"


def review_fn(app: FastAPI) -> ReviewFn:
    """Runs the real review pipeline for seeded subscriptions (so Story B's Lumen review exists)."""
    async def run(merchant_id: str, plan_key: str, user_id: str, day: int) -> str | None:
        svc: Services = app.state.services
        cap = await app.state.capture.capture(f"/shop/{merchant_id}", "http://127.0.0.1:8000/")
        plan = await svc.gw.get_plan(svc.gw.plan_id(plan_key), Ctx(actor="system", user_id=user_id))
        data = await app.state.auditor.review(cap, plan, merchant=svc.merchant(merchant_id), plan_key=plan_key,
                                              signup_day=day, user_id=user_id)
        review = save_review(svc.store, data, day)
        svc.store.audit.append(actor="system", event="review_run", user_id=user_id, result=data.mode,
                               reason=f"{merchant_id}: risk {data.risk_score}/100 (demo seed)",
                               details={"review_id": review.id, "risk": data.risk_score, "types": data.types()})
        return review.id
    return run


def _control(svc: Services, action: str, **details: Any) -> None:
    svc.store.audit.append(actor="user", event="demo_control", reason=action, details={"action": action, **details})


@router.post("/reset")
async def reset(request: Request, svc: Services = Depends(get_services)) -> dict[str, object]:
    async with svc.store.alocked():
        svc.store.reset()
        _control(svc, "reset")
    svc.policy = type(svc.policy)()  # fresh rate-limit window
    await seed_demo(svc, review_fn(request.app))
    return {"ok": True, "sim_day": svc.day}


@router.post("/advance")
async def advance(days: int = 1, to_day: int | None = None, svc: Services = Depends(get_services)) -> dict[str, int]:
    if to_day is not None and to_day < svc.day:
        raise HTTPException(400, "The sim clock only moves forward; use Reset to start over")
    if not 0 <= days <= 400:
        raise HTTPException(400, "days must be between 0 and 400")
    _control(svc, "advance", days=days, to_day=to_day)
    return {"sim_day": await clock_advance(svc, days, to_day=to_day)}


@router.post("/price-rise")
async def price_rise(svc: Services = Depends(get_services)) -> dict[str, str]:
    """Framewise raises its plan price (sandbox: a real update-pricing-schemes call), then SubGuard diffs it."""
    merchant = svc.merchant("framewise")
    plan_id = svc.gw.plan_id(PRICE_RISE_PLAN)
    ctx = Ctx(actor="merchant_sim", merchant=merchant)
    plan = await svc.gw.get_plan(plan_id, ctx)
    seq = max(i for i, c in enumerate(plan.billing_cycles, start=1) if c.tenure_type == "REGULAR")
    new = svc.settings.pricing.framewise_rise_price
    _control(svc, "price_rise", plan=PRICE_RISE_PLAN, price=str(new))
    await svc.gw.update_pricing(plan_id, seq, new, plan.currency, ctx)
    await watch_prices(svc)
    return {"plan_id": plan_id, "new_price": str(new)}


@router.post("/toggle-fair-trial/{merchant_id}")
async def toggle_fair_trial(merchant_id: str, svc: Services = Depends(get_services)) -> dict[str, object]:
    async with svc.store.aedit("merchants") as merchants:
        m = next((x for x in merchants.items if x.id == merchant_id), None)
        if m is None:
            raise HTTPException(404, "Unknown merchant")
        m.fair_trial_member = not m.fair_trial_member
        member = m.fair_trial_member
    subs = {s.id: s for s in svc.store.load("subscriptions").items if s.merchant_id == merchant_id}
    async with svc.store.aedit("timers") as timers:  # Layer 2 timers fire at deadline - 2
        for t in timers.items:
            if t.subscription_id in subs and t.status == "PENDING" and t.kind == "trial" and t.deadline_day is not None:
                sub = subs[t.subscription_id]
                d = compute_deadlines(sub.signup_day, t.billing_day or sub.next_billing_day or 0,
                                      (t.billing_day or 0) - t.deadline_day - 1, layer2=not member)
                t.layer2, t.fire_day, t.reminder_day = d.layer2, d.timer_fire_day, d.reminder_day
    _control(svc, "toggle_fair_trial", merchant=merchant_id, fair_trial_member=member)
    return {"merchant": merchant_id, "fair_trial_member": member}

"""Registering a confirmed (ACTIVE) PayPal subscription: consent snapshot, review link, Day-0 protection."""

from __future__ import annotations

from app.core.services import Services
from app.core.timers import on_registered
from app.integrations.paypal_gateway import Ctx
from app.integrations.paypal_types import SubscriptionView, first_charge_day, first_paid_price
from app.models import ConsentSnapshot, Subscription
from app.store import utcnow


class OwnershipError(Exception):
    pass


async def register_active(svc: Services, view: SubscriptionView, *, merchant_id: str, plan_key: str, user_id: str,
                          review_id: str | None = None,
                          signup_day: int | None = None) -> tuple[Subscription, bool]:
    """Returns (subscription, created). Only call with a PayPal status of ACTIVE (corner case 2)."""
    merchant = svc.merchant(merchant_id)
    ctx = Ctx(actor="user", user_id=user_id, merchant=merchant)
    plan = await svc.gw.get_plan(view.plan_id or svc.gw.plan_id(plan_key), ctx)
    day = svc.day if signup_day is None else signup_day
    local_id = f"sub-{view.id}"
    async with svc.store.aedit("subscriptions") as subs:
        existing = next((s for s in subs.items if s.id == local_id), None)
        if existing and existing.owner_id != user_id:
            raise OwnershipError("This subscription belongs to another user")
        if existing:
            return existing, False
        sub = Subscription(
            id=local_id, paypal_id=view.id, plan_key=plan_key, plan_id=plan.id, merchant_id=merchant.id,
            owner_id=user_id, status="ACTIVE", signup_day=day,
            next_billing_day=first_charge_day(plan.billing_cycles, day),
            registered_at=utcnow(),
            consent_snapshot=ConsentSnapshot(taken_at=utcnow(), sim_day=day, currency=plan.currency,
                                             price=first_paid_price(plan.billing_cycles),
                                             billing_cycles=plan.billing_cycles),
        )
        subs.items.append(sub)
    if review_id:
        async with svc.store.aedit("reviews") as reviews:
            rev = next((r for r in reviews.items if r.id == review_id and r.merchant_id == merchant.id
                        and r.subscription_id is None), None)
            if rev is not None:
                rev.subscription_id = sub.id
    svc.store.audit.append(actor="user", event="subscription_registered", user_id=user_id, subscription_id=sub.id,
                           status_after="ACTIVE", transport=svc.gw.full.transport,  # type: ignore[arg-type]
                           details={"paypal_id": sub.paypal_id, "plan_key": plan_key,
                                    "signup_day": day})
    svc.store.audit.append(actor="system", event="consent_snapshot", user_id=user_id, subscription_id=sub.id,
                           details={"price": str(sub.consent_snapshot.price), "currency": plan.currency,  # type: ignore[union-attr]
                                    "cycles": len(plan.billing_cycles), "source": "paypal_plan"})
    await on_registered(svc, sub)
    return sub, True

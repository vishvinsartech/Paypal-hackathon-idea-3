"""The "Subscribed via PayPal ✓" card (D-113): status, plan and billing cycles read LIVE from PayPal, never
assumed from our JSON files. Every read is audited with PayPal's debug ids; after a cancel the card also shows
our cancel call's PayPal-Request-Id and debug id (from the paypal_cancel audit entry)."""

from __future__ import annotations

from typing import Any

from app.core.services import Services
from app.integrations.paypal_gateway import Ctx
from app.integrations.paypal_types import PayPalError
from app.models import BillingCycleDef, Subscription

UNIT = {"DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}


def cycle_text(svc: Services, c: BillingCycleDef, currency: str, first_paid: bool) -> str:
    """One PayPal billing cycle in plain English: '10-day trial $0', '3 × $24.99/month', 'then $49.99/month'."""
    unit = UNIT[c.interval_unit]
    every = unit if c.interval_count == 1 else f"{c.interval_count} {unit}s"
    if c.price == 0:
        length = c.interval_count * max(1, c.total_cycles)
        return f"{length}-{unit} trial {svc.settings.pricing.money(0, currency)}"
    price = f"{svc.settings.pricing.money(c.price, currency)}/{every}"
    if c.total_cycles == 0:
        return price if first_paid else f"then {price}"
    return f"{c.total_cycles} × {price}"


def _created(svc: Services, sub: Subscription) -> dict[str, Any] | None:
    """Our server-side create call for this subscription (its PayPal-Request-Id), if SubGuard created it."""
    rows = [e for e in svc.store.audit.query(event="paypal_subscription_created")
            if e.details.get("paypal_id") == sub.paypal_id]
    return {"request_id": rows[-1].paypal_request_id, "transport": rows[-1].transport} if rows else None


def _last_cancel(svc: Services, sub: Subscription) -> dict[str, Any] | None:
    rows = [e for e in svc.store.audit.query(subscription_id=sub.id, event="paypal_cancel")
            if (e.result or "").startswith("ok")]
    if not rows:
        return None
    e = rows[-1]
    return {"request_id": e.paypal_request_id, "debug_id": e.paypal_debug_id, "transport": e.transport,
            "day": e.sim_day, "by": e.actor}


async def paypal_card(svc: Services, sub: Subscription) -> dict[str, Any]:
    base: dict[str, Any] = {"subscription_id": sub.id, "paypal_id": sub.paypal_id, "local_status": sub.status,
                            "sandbox": svc.settings.is_sandbox, "source": "PayPal Sandbox (live)"
                            if svc.settings.is_sandbox else "Mock PayPal (simulated; run in sandbox mode for real)",
                            "autopay_url": svc.settings.paypal_autopay_url if svc.settings.is_sandbox else None}
    ctx = Ctx(actor="system", user_id=sub.owner_id, subscription_id=sub.id, merchant=svc.merchant(sub.merchant_id))
    try:
        v = await svc.gw.verify(sub.paypal_id, ctx)
    except PayPalError as exc:
        svc.store.audit.append(actor="system", event="paypal_subscription_verified", user_id=sub.owner_id,
                               subscription_id=sub.id, transport=exc.transport, paypal_debug_id=exc.debug_id,  # type: ignore[arg-type]
                               result=f"error:{exc.summary()}", details={"paypal_id": sub.paypal_id})
        return {**base, "ok": False, "error": "Couldn't reach PayPal right now. Try again in a moment."}
    cycles, first_paid = [], True
    for c in v.plan.billing_cycles:
        cycles.append({"tenure_type": c.tenure_type, "price": str(c.price), "interval_unit": c.interval_unit,
                       "interval_count": c.interval_count, "total_cycles": c.total_cycles,
                       "text": cycle_text(svc, c, v.plan.currency, first_paid and c.price > 0)})
        first_paid = first_paid and c.price == 0
    cancel = _last_cancel(svc, sub) if v.subscription.status == "CANCELLED" else None
    created = _created(svc, sub)
    svc.store.audit.append(actor="system", event="paypal_subscription_verified", user_id=sub.owner_id,
                           subscription_id=sub.id, transport=v.transport,  # type: ignore[arg-type]
                           paypal_request_id=(cancel or created or {}).get("request_id"),
                           paypal_debug_id=v.subscription_debug_id, status_after=v.subscription.status, result="ok",
                           details={"paypal_id": sub.paypal_id, "plan_id": v.plan.id,
                                    "plan_debug_id": v.plan_debug_id, "local_status": sub.status})
    return {**base, "ok": True, "status": v.subscription.status, "plan_id": v.plan.id, "plan_name": v.plan.name,
            "currency": v.plan.currency, "cycles": cycles, "cycles_text": " · ".join(c["text"] for c in cycles),
            "next_billing_time": v.subscription.next_billing_time, "transport": v.transport,
            "debug_id": v.subscription_debug_id, "plan_debug_id": v.plan_debug_id,
            "checked_at": v.checked_at.isoformat(), "matches_local": v.subscription.status == sub.status,
            "cancel": cancel, "created": created}

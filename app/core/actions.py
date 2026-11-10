"""Cancelling, the only way: propose (card + token) -> user confirms -> policy -> gateway -> per-item results.

R7: results come only from the gateway's outcome (PayPal status re-read after the cancel). A multi-cancel
reports each item (corner case 34); nothing is claimed for an item that failed.
After a confirmed PayPal cancel, the merchant's written-notice email is only DRAFTED (notices.py); the user
reviews and sends it. Layer 2 merchants (not in Fair Trial) can't be cancelled by SubGuard: it drafts the email and
sends an ACTION NEEDED alert with a one-tap link to PayPal's Automatic payments page instead.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.core.alerts import action, send_alert
from app.core.notices import create_draft
from app.core.policy import Decision
from app.core.savings import year_one_cost
from app.core.services import Services
from app.integrations.paypal_gateway import Ctx
from app.integrations.paypal_types import PayPalError
from app.models import ConfirmToken, Subscription
from app.store import utcnow

DECISION_ACTIONS = {"keep", "cancel"}  # moot once the subscription is cancelled or kept
UNDO_WARNING = "This can't be undone; you'd need to sign up again."


class CardItem(BaseModel):
    subscription_id: str
    merchant: str
    plan: str
    per_year: Decimal
    per_year_text: str


class ConfirmCard(BaseModel):
    token: str
    expires_at: datetime
    user_id: str
    reason: str
    items: list[CardItem]
    total_per_year: Decimal
    total_text: str
    warning: str = UNDO_WARNING


class ItemResult(BaseModel):
    subscription_id: str
    merchant: str
    ok: bool
    status: str | None = None
    outcome: Literal["cancelled", "already_cancelled", "failed", "blocked", "action_needed"]
    message: str
    rule_id: str | None = None
    protected_year_usd: Decimal | None = None
    transport: str | None = None  # sdk | mcp | rest | mock: shown on the chat's tool chip
    notice_id: str | None = None  # the cancellation email draft, created after the PayPal cancel


async def year_cost(svc: Services, sub: Subscription) -> Decimal:
    """Money at stake per year, from the PayPal plan as it is now (falls back to the consent snapshot)."""
    try:
        plan = await svc.gw.get_plan(sub.plan_id, Ctx(actor="system", user_id=sub.owner_id, subscription_id=sub.id))
        return year_one_cost(plan.billing_cycles)
    except PayPalError:
        return year_one_cost(sub.consent_snapshot.billing_cycles) if sub.consent_snapshot else Decimal("0")


async def propose_cancel(svc: Services, user_id: str, sub_ids: list[str], reason: str) -> ConfirmCard | Decision:
    issued = svc.policy.issue_token(svc.store, user_id, sub_ids)
    if isinstance(issued, Decision):
        return issued
    tok: ConfirmToken = issued
    items = []
    for sid in tok.subscription_ids:
        sub = svc.sub(sid)
        assert sub is not None  # ownership checked by the policy
        per_year = await year_cost(svc, sub)
        merchant = svc.merchant(sub.merchant_id)
        plan = next((p.name for p in merchant.plans if p.key == sub.plan_key), sub.plan_key)
        items.append(CardItem(subscription_id=sid, merchant=merchant.name, plan=plan,
                              per_year=per_year, per_year_text=f"{svc.money(per_year)}/yr"))
    total = sum((i.per_year for i in items), start=Decimal("0"))
    return ConfirmCard(token=tok.token, expires_at=tok.expires_at, user_id=user_id, reason=reason, items=items,
                       total_per_year=total, total_text=f"{svc.money(total)}/yr")


async def layer2_handoff(svc: Services, sub: Subscription, why: str) -> None:
    merchant = svc.merchant(sub.merchant_id)
    notice = await create_draft(svc, sub, by_timer=True)
    await send_alert(
        svc, user_id=sub.owner_id, key=f"layer2:{sub.id}", kind="action_needed", level="action_needed",
        title=f"ACTION NEEDED: cancel {merchant.name} in PayPal",
        body=(f"{why} {merchant.name} isn't a Fair Trial merchant, so only you can stop it in PayPal. "
              f"Tap below, find {merchant.name} under Automatic payments and cancel it. "
              "Your cancellation email is ready to review and send."),
        actions=[action("open_autopay", "Open PayPal Automatic payments", url=svc.settings.paypal_autopay_url),
                 action("review_email", "Review email", notice_id=notice.id)],
        subscription_id=sub.id, cta_url=svc.settings.paypal_autopay_url)


async def cancel_one(svc: Services, sub: Subscription, *, actor: str, rule_id: str, reason: str,
                     timer_id: str | None = None) -> ItemResult:
    merchant = svc.merchant(sub.merchant_id)
    base = {"subscription_id": sub.id, "merchant": merchant.name, "rule_id": rule_id}
    if sub.status == "CANCELLED":
        return ItemResult(**base, ok=True, status="CANCELLED", outcome="already_cancelled",
                          message=f"{merchant.name} was already cancelled.")
    if not merchant.fair_trial_member:
        await layer2_handoff(svc, sub, "You asked me to cancel it.")
        return ItemResult(**base, ok=False, status=sub.status, outcome="action_needed",
                          message=f"{merchant.name} must be cancelled by you in PayPal (link sent).")
    blocked = svc.policy.take_write(svc.store, sub.owner_id, sub.id, actor)
    if blocked is not None:
        return ItemResult(**base, ok=False, status=sub.status, outcome="blocked", message=blocked.reason)
    per_year = await year_cost(svc, sub)
    out = await svc.gw.cancel(sub.paypal_id, reason, Ctx(actor=actor, user_id=sub.owner_id, subscription_id=sub.id,
                                                         merchant=merchant, rule_id=rule_id,
                                                         extra={"reason": reason}))
    if not out.ok:
        return ItemResult(**base, ok=False, status=out.status_after or sub.status, outcome="failed",
                          message=f"PayPal didn't confirm the cancel ({out.error}).", transport=out.transport)
    async with svc.store.aedit("subscriptions") as subs:
        stored = next(s for s in subs.items if s.id == sub.id)
        stored.cancelled_by = "timer" if actor == "timer" else "user"
        stored.cancelled_day = svc.day
        stored.protected_year_usd = per_year
    async with svc.store.aedit("alerts") as alerts:
        for a in alerts.items:
            offered = {x["action"] for x in a.actions}
            if a.subscription_id == sub.id and a.acknowledged_at is None and offered & DECISION_ACTIONS:
                a.acknowledged_at = utcnow()
    async with svc.store.aedit("timers") as timers:
        for t in timers.items:
            if t.subscription_id == sub.id and t.status == "PENDING" and t.id != timer_id:
                t.status = "CANCELLED"
                t.note = "subscription cancelled"
    return ItemResult(**base, ok=True, status="CANCELLED",
                      outcome="already_cancelled" if out.already_cancelled else "cancelled",
                      message=f"{merchant.name}: cancelled in PayPal.", protected_year_usd=per_year,
                      transport=out.transport)


async def confirm_cancelled(svc: Services, sub: Subscription, result: ItemResult, *, by_timer: bool) -> str:
    """After a confirmed PayPal cancel (the user's tap or the safety timer): tell the user it's done and draft the
    written cancellation email the merchant's terms require. The email is never sent here: only the user's click
    in the preview sends it (D-104). Idempotent per subscription. Returns the draft's notice id."""
    merchant = svc.merchant(sub.merchant_id)
    notice = await create_draft(svc, sub, by_timer=by_timer)
    who = "Your safety timer cancelled" if by_timer else "I cancelled"
    await send_alert(svc, user_id=sub.owner_id, key=f"cancelled:{sub.id}", kind="cancelled",
                     level="warning" if by_timer else "info", title="Cancelled in PayPal. You won't be charged.",
                     body=(f"{who} {merchant.name} in PayPal (status {result.status}). "
                           "Your cancellation email is ready to review and send."),
                     actions=[action("review_email", "Review email", notice_id=notice.id)], subscription_id=sub.id)
    return notice.id


async def cancel_confirmed(svc: Services, user_id: str, sub_ids: list[str], token: str | None,
                           requested_by: str = "user") -> list[ItemResult] | Decision:
    decisions = svc.policy.check_user_cancel(svc.store, user_id, sub_ids, token, requested_by)
    if not decisions[0].allowed:
        return decisions[0]
    results = []
    for d in decisions:
        sub = svc.sub(d.subscription_id or "")
        if sub is not None:
            result = await cancel_one(svc, sub, actor="user", rule_id="R1", reason="Cancelled by the user")
            if result.outcome == "cancelled":
                result.notice_id = await confirm_cancelled(svc, sub, result, by_timer=False)
            results.append(result)
    return results

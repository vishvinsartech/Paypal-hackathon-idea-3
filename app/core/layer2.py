"""Layer 2 (A5): merchants that aren't Fair Trial members. SubGuard can't cancel them, so Priya does it in PayPal's
Automatic payments page, and SubGuard watches PayPal (read-only GETs) until it shows CANCELLED.

No PayPal write happens here. In mock mode, `/demo/paypal-autopay` stands in for PayPal's own page: its Cancel
button is Priya acting in PayPal (actor `user`), not SubGuard, so no policy rule applies (D-145).
"""

from __future__ import annotations

from app.core.alerts import action, send_alert
from app.core.escalation import apply_status
from app.core.services import Services
from app.integrations.paypal_gateway import Ctx
from app.integrations.paypal_types import PayPalError
from app.models import Alert, Subscription
from app.store import utcnow

HANDOFF_KINDS = frozenset({"action_needed", "urgent"})


def open_handoffs(alerts: list[Alert], user_id: str) -> list[Alert]:
    """Unhandled ACTION NEEDED cards (the Layer 2 handoff), newest first."""
    return [a for a in reversed(alerts) if a.user_id == user_id and a.kind == "action_needed"
            and a.acknowledged_at is None and (a.idempotency_key or "").startswith("layer2:")]


async def check_paypal(svc: Services, sub: Subscription) -> tuple[str, str | None]:
    """One read-only GET. Records a PayPal-side change (the poller's `apply_status`); once PayPal shows CANCELLED
    after a handoff, closes the ACTION NEEDED card and says so. Returns (status, debug id)."""
    try:
        verified = await svc.gw.verify(sub.paypal_id, Ctx(actor="system", user_id=sub.owner_id,
                                                          subscription_id=sub.id, extra={"purpose": "layer2_check"}))
    except PayPalError:
        return sub.status, None
    status, debug_id = verified.subscription.status or sub.status, verified.subscription_debug_id
    await apply_status(svc, sub.id, status, "layer2_check")
    if status == "CANCELLED":
        await close_handoff(svc, sub, debug_id)
    return status, debug_id


async def close_handoff(svc: Services, sub: Subscription, debug_id: str | None) -> None:
    handed_off = False
    async with svc.store.aedit("alerts") as alerts:
        for a in alerts.items:
            if a.subscription_id == sub.id and a.acknowledged_at is None and a.kind in HANDOFF_KINDS:
                a.acknowledged_at = utcnow()
            handed_off = handed_off or (a.idempotency_key == f"layer2:{sub.id}")
    if not handed_off:
        return
    name = svc.merchant(sub.merchant_id).name
    notice = next((n for n in svc.store.load("notices").items if n.subscription_id == sub.id), None)
    email = (" Your cancellation email is ready to review and send." if notice and notice.status != "sent" else "")
    _, created = await send_alert(
        svc, user_id=sub.owner_id, key=f"layer2-done:{sub.id}", kind="cancelled", level="info",
        title=f"PayPal shows {name} CANCELLED. You won't be charged.",
        body=(f"You cancelled {name} in PayPal's Automatic payments, and SubGuard checked PayPal: "
              f"status CANCELLED.{email}"),
        actions=[action("review_email", "Review email", notice_id=notice.id)] if email and notice else [],
        subscription_id=sub.id)
    if created:
        svc.store.audit.append(actor="system", event="layer2_cancel_seen", user_id=sub.owner_id,
                               subscription_id=sub.id, status_after="CANCELLED", paypal_debug_id=debug_id,
                               transport=svc.gw.full.transport,  # type: ignore[arg-type]
                               reason=f"Checked PayPal: {name} is CANCELLED (cancelled by Priya in PayPal)")

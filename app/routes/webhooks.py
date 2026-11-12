"""PayPal webhooks (spec 7.1): /webhooks/paypal.

Sandbox mode verifies each event with /v1/notifications/verify-webhook-signature (PAYPAL_WEBHOOK_ID).
Localhost can't receive webhooks, so the 10-second poller is the main path; this route matters behind a
tunnel or on Render. Corner case 6: events are deduplicated by event id, and a status change already seen by
the poller (or an earlier webhook) is a no-op (`apply_status` dedupes by status transition).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.escalation import apply_status
from app.core.services import Services
from app.routes.actions import get_services

router = APIRouter()
SEEN_LIMIT = 500
STATUS_EVENTS = {"BILLING.SUBSCRIPTION.ACTIVATED": "ACTIVE", "BILLING.SUBSCRIPTION.CANCELLED": "CANCELLED",
                 "BILLING.SUBSCRIPTION.SUSPENDED": "SUSPENDED", "BILLING.SUBSCRIPTION.EXPIRED": "EXPIRED"}
HANDLED = {*STATUS_EVENTS, "BILLING.SUBSCRIPTION.UPDATED", "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
           "PAYMENT.SALE.COMPLETED"}


def paypal_sub_id(event: dict[str, Any]) -> str | None:
    resource = event.get("resource") or {}
    if str(event.get("event_type", "")).startswith("PAYMENT.SALE"):
        return resource.get("billing_agreement_id")
    return resource.get("id")


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, svc: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        event = await request.json()
    except ValueError:
        raise HTTPException(400, "Body must be JSON") from None
    if not isinstance(event, dict) or not event.get("id") or not event.get("event_type"):
        raise HTTPException(400, "Not a PayPal webhook event")
    event_id, kind = str(event["id"]), str(event["event_type"])
    if svc.settings.is_sandbox:
        verify = getattr(request.app.state, "verify_webhook", None)
        if verify is None or not await verify(dict(request.headers), event):
            svc.store.audit.append(actor="system", event="webhook_rejected", reason="signature not verified",
                                   details={"event_id": event_id, "event_type": kind})
            raise HTTPException(400, "Webhook signature could not be verified")
    async with svc.store.aedit("state") as state:
        duplicate = event_id in state.webhook_event_ids
        if not duplicate:
            state.webhook_event_ids = [*state.webhook_event_ids, event_id][-SEEN_LIMIT:]
    if duplicate:
        svc.store.audit.append(actor="system", event="webhook_duplicate", details={"event_id": event_id})
        return {"status": "duplicate"}
    pid = paypal_sub_id(event)
    sub = next((s for s in svc.store.load("subscriptions").items if s.paypal_id == pid), None)
    svc.store.audit.append(actor="system", event="webhook_received", user_id=sub.owner_id if sub else None,
                           subscription_id=sub.id if sub else None, transport="rest",
                           result="handled" if kind in HANDLED and sub else "ignored",
                           details={"event_id": event_id, "event_type": kind, "paypal_id": pid})
    if sub is None or kind not in HANDLED:
        return {"status": "ignored"}
    changed = False
    if kind in STATUS_EVENTS:
        changed = await apply_status(svc, sub.id, STATUS_EVENTS[kind], "webhook")
    elif kind == "BILLING.SUBSCRIPTION.UPDATED":
        status = str((event.get("resource") or {}).get("status", ""))
        changed = await apply_status(svc, sub.id, status, "webhook") if status else False
    return {"status": "processed", "changed": changed}

"""Alerts to the user (in-app + email/SMS) and written cancellation notices to merchants.

Alerts are idempotent by key: jumping several days or re-running a tick never sends twice (corner case 14).
Info alerts are in-app only; warning / urgent / action_needed alerts also go out on the user's channels.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Literal

from app.core.services import Services
from app.models import Alert, Notice, Subscription
from app.store import utcnow

Level = Literal["info", "warning", "urgent", "action_needed"]


def action(kind: str, label: str, **extra: str) -> dict[str, str]:
    return {"action": kind, "label": label, **extra}


async def send_alert(svc: Services, *, user_id: str, key: str, kind: str, level: Level, title: str, body: str,
                     actions: list[dict[str, str]] | None = None, subscription_id: str | None = None,
                     cta_url: str = "") -> tuple[Alert, bool]:
    """Returns (alert, created). An existing alert with the same idempotency key is returned unchanged."""
    store = svc.store
    async with store.aedit("alerts") as alerts:
        existing = next((a for a in alerts.items if a.idempotency_key == key), None)
        if existing is not None:
            return existing, False
        alert = Alert(id=f"al-{secrets.token_hex(5)}", user_id=user_id, kind=kind, level=level, title=title,
                      body=body, actions=actions or [], subscription_id=subscription_id, sim_day=svc.day,
                      created_at=utcnow(), idempotency_key=key, delivery={"in_app": svc.notifier.in_app()})
        alerts.items.append(alert)
    user = svc.user(user_id)
    channels = [c for c in (user.settings.channels if user else []) if c != "in_app"] if level != "info" else []
    to = {"email": user.email, "phone": user.phone} if user else {}
    external = await svc.notifier.send(kind="user_alert", to=to, subject=title, body=body, idempotency_key=key,
                                       channels=channels, cta_url=cta_url)
    async with store.aedit("alerts") as alerts:
        stored = next(a for a in alerts.items if a.id == alert.id)
        stored.delivery.update(external)
        alert = stored
    store.audit.append(actor="system", event="alert_sent", user_id=user_id, subscription_id=subscription_id,
                       result=",".join(f"{k}:{v}" for k, v in alert.delivery.items()), reason=title,
                       details={"alert_id": alert.id, "kind": kind, "level": level, "key": key,
                                "target": svc.notifier.target})
    return alert, True


def notice_body(svc: Services, sub: Subscription, merchant_name: str) -> str:
    user = svc.user(sub.owner_id)
    return (f"To {merchant_name} support,\n\n"
            f"Please cancel my subscription (PayPal subscription id {sub.paypal_id}, plan {sub.plan_key}) "
            f"with effect before the next billing date. This is my written notice as required by your terms.\n"
            f"Account email: {user.email if user else ''}\n\n"
            f"Sent on my behalf by SubGuard on sim day {svc.day}.\n")


async def send_cancellation_notice(svc: Services, sub: Subscription) -> Notice:
    """The written notice the merchant's terms require, stored with a SHA-256 proof (corner case 38)."""
    store = svc.store
    existing = next((n for n in store.load("notices").items if n.subscription_id == sub.id), None)
    if existing is not None:
        return existing
    merchant = svc.merchant(sub.merchant_id)
    body = notice_body(svc, sub, merchant.name)
    subject = f"Cancellation notice: subscription {sub.paypal_id}"
    result = await svc.notifier.send(kind="merchant_cancellation", to={"email": merchant.support_email},
                                     subject=subject, body=body, idempotency_key=f"notice:{sub.id}",
                                     channels=["email"])
    notice = Notice(id=f"nt-{secrets.token_hex(5)}", subscription_id=sub.id, merchant_id=merchant.id,
                    sim_day=svc.day, to=merchant.support_email, subject=subject, body=body,
                    sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(), sent_at=utcnow(),
                    delivery=result.get("email", "failed"))
    async with store.aedit("notices") as notices:
        notices.items.append(notice)
    store.audit.append(actor="system", event="cancellation_notice_sent", user_id=sub.owner_id,
                       subscription_id=sub.id, result=notice.delivery,
                       details={"notice_id": notice.id, "to": notice.to, "sha256": notice.sha256})
    return notice

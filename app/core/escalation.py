"""One `tick(day)` = everything SubGuard does on a sim day (the demo story, spec 2 / 7.4).

Order: sync PayPal statuses -> early trial end (exports) -> timer check-ins -> timer firing ->
Layer 2 urgent checks -> billing-day events (blocked-charge proof) -> reminders the chat scheduled.
Every alert has an idempotency key, so re-running a day never double-sends.
"""

from __future__ import annotations

import re

from app.core import timers as tm
from app.core.alerts import action, send_alert
from app.core.services import Services
from app.core.sub_dates import day_text
from app.core.usage import exports
from app.integrations.paypal_gateway import Ctx
from app.integrations.paypal_types import DAYS_PER_UNIT, PayPalError, cycle_days
from app.models import Subscription
from app.store import utcnow


async def apply_status(svc: Services, sub_id: str, status: str, source: str) -> bool:
    """Record a PayPal-side status change once. The poller and webhooks both call this, so the same change seen
    twice is a no-op (corner case 6: dedupe by status transition). Returns True if something changed."""
    async with svc.store.aedit("subscriptions") as subs:
        s = next((x for x in subs.items if x.id == sub_id), None)
        if s is None or not status or s.status == status:
            return False
        before, s.status, s.last_synced_at = s.status, status, utcnow()  # type: ignore[assignment]
        if status == "CANCELLED" and s.cancelled_by is None:
            s.cancelled_by, s.cancelled_day = "external", svc.day
        owner = s.owner_id
    async with svc.store.aedit("timers") as timers:  # corner case 5: suspended/expired/cancelled -> no timer
        for t in timers.items:
            if t.subscription_id == sub_id and t.status == "PENDING" and status != "ACTIVE":
                t.status, t.note = "CANCELLED", f"PayPal status changed to {status}"
    svc.store.audit.append(actor="system", event="status_sync", user_id=owner, subscription_id=sub_id,
                           status_before=before, status_after=status,
                           transport=svc.gw.full.transport,  # type: ignore[arg-type]
                           details={"source": source})
    return True


async def sync_statuses(svc: Services) -> None:
    """The poller's job (also run each tick): PayPal-side changes, e.g. merchant suspends (corner case 5)."""
    for sub in [s for s in svc.store.load("subscriptions").items if s.status in ("ACTIVE", "SUSPENDED")]:
        try:
            view = await svc.gw.get_subscription(sub.paypal_id, Ctx(actor="system", user_id=sub.owner_id,
                                                                     subscription_id=sub.id))
        except PayPalError:
            continue
        await apply_status(svc, sub.id, view.status or "", "poller")


async def early_trial_end(svc: Services, day: int) -> None:
    """Corner case 27: the terms end the trial early after N exports. Too many exports -> warn that the trial may
    already have converted, and move the timer's deadline to today (the auto-timer can't warn 24 h ahead now)."""
    for timer in [t for t in svc.store.load("timers").items if t.status == "PENDING" and t.kind == "trial"]:
        sub = svc.sub(timer.subscription_id)
        review = tm.review_for(svc, sub) if sub else None
        clause = next((c for c in review.data.clauses if c.type == "EARLY_TRIAL_TERMINATION"), None) if review else None
        limit = re.search(r"more than (\d+)", clause.quote) if clause else None
        if sub is None or limit is None:
            continue
        done = exports(svc.store, sub.owner_id, sub.merchant_id, sub.signup_day, day)
        if done <= int(limit.group(1)):
            continue
        name = svc.merchant(sub.merchant_id).name
        _, created = await send_alert(
            svc, user_id=sub.owner_id, key=f"early-end:{sub.id}", kind="early_trial_end", level="urgent",
            title=f"{name}: your trial may have ended early",
            body=(f"You've exported {done} documents. {name}'s terms end the trial after more than "
                  f"{limit.group(1)}, so it may already be a paid subscription. Decide today: cancel or keep?"),
            actions=[action("cancel", "Cancel now"), action("keep", "Keep")], subscription_id=sub.id)
        if created:
            async with svc.store.aedit("timers") as timers:
                t = next(x for x in timers.items if x.id == timer.id)
                t.deadline_day, t.note = day, f"trial may have ended early ({done} exports)"
            svc.store.audit.append(actor="system", event="early_trial_end_risk", user_id=sub.owner_id,
                                   subscription_id=sub.id, details={"exports": done, "limit": int(limit.group(1))})


async def run_timers(svc: Services, day: int) -> None:
    for timer in [t for t in svc.store.load("timers").items if t.status == "PENDING"]:
        if not timer.warning_delivered and day >= (timer.reminder_day if timer.reminder_day is not None else day):
            if day < (timer.billing_day or day + 1):
                await tm.warn(svc, timer, day)
    for timer in [t for t in svc.store.load("timers").items if t.status == "PENDING" and day >= t.fire_day]:
        await tm.fire(svc, timer, day)


async def layer2_urgent(svc: Services, day: int) -> None:
    """Layer 2: still ACTIVE 24 sim-hours before the charge -> urgent alert."""
    fired = {t.subscription_id for t in svc.store.load("timers").items if t.status in ("FIRED", "FAILED")}
    for sub in svc.store.load("subscriptions").items:
        if sub.id in fired and sub.status == "ACTIVE" and sub.next_billing_day == day + 1:
            name = svc.merchant(sub.merchant_id).name
            await send_alert(svc, user_id=sub.owner_id, key=f"layer2-urgent:{sub.id}", kind="urgent", level="urgent",
                             title=f"URGENT: {name} charges you tomorrow",
                             body=f"{name} is still active in PayPal. Cancel it under Automatic payments today.",
                             actions=[action("open_autopay", "Open PayPal Automatic payments",
                                             url=svc.settings.autopay_link)],
                             subscription_id=sub.id, cta_url=svc.settings.autopay_link)


PROOF_OK = "Checked PayPal: no active subscription, so no charge can be taken."
PROOF_UNREACHABLE = ("Couldn't reach PayPal to check today. SubGuard's records show the subscription was "
                     "cancelled in PayPal.")


async def charge_day_proof(svc: Services, sub: Subscription, name: str, day: int) -> None:
    """B8: on the first-charge day SubGuard (not PayPal: PayPal did nothing, the sim clock moved) does a fresh
    live GET and stores PayPal's status and debug id as the proof. Only claims what the read confirms (R7)."""
    ctx = Ctx(actor="system", user_id=sub.owner_id, merchant=svc.merchant(sub.merchant_id))
    try:
        seen = await svc.gw.verify(sub.paypal_id, ctx)
    except PayPalError as exc:
        status, debug, body, result = None, None, PROOF_UNREACHABLE, f"error: {exc}"
    else:
        status, debug = seen.subscription.status, seen.subscription_debug_id
        result = "no_active_subscription" if status != "ACTIVE" else "still_active"
        body = PROOF_OK if status != "ACTIVE" else (f"PayPal still shows {name} as ACTIVE. Check Automatic "
                                                    "payments in PayPal today.")
    await send_alert(svc, user_id=sub.owner_id, key=f"blocked-charge:{sub.id}:{day}", kind="blocked_charge",
                     level="info" if result == "no_active_subscription" else "urgent",
                     title=f"{name}: first charge due today", body=body, subscription_id=sub.id)
    svc.store.audit.append(actor="system", event="charge_blocked", user_id=sub.owner_id, subscription_id=sub.id,
                           status_after=status, paypal_debug_id=debug, transport=svc.gw.full.transport,  # type: ignore[arg-type]
                           result=result, reason=body,
                           details={"checked_by": "SubGuard", "paypal_status": status, "paypal_id": sub.paypal_id})


async def billing_day(svc: Services, day: int) -> None:
    for sub in [s for s in svc.store.load("subscriptions").items if s.next_billing_day == day]:
        name = svc.merchant(sub.merchant_id).name
        if sub.status == "CANCELLED":
            await charge_day_proof(svc, sub, name, day)
        elif sub.status == "ACTIVE":
            cycles = sub.consent_snapshot.billing_cycles if sub.consent_snapshot else []
            step = next((cycle_days(c) for c in cycles if c.price > 0), DAYS_PER_UNIT["MONTH"])
            async with svc.store.aedit("subscriptions") as subs:
                s = next(x for x in subs.items if x.id == sub.id)
                s.next_billing_day = day + step
            svc.store.audit.append(actor="system", event="charge_due", user_id=sub.owner_id, subscription_id=sub.id,
                                   reason="Billing date reached (simulated; PayPal sandbox time doesn't advance)",
                                   details={"next_billing_day": day + step})


async def scheduled_reminders(svc: Services, day: int) -> None:
    """Reminders the chat agent scheduled (schedule_reminder tool)."""
    for rem in [r for r in svc.store.load("state").reminders if not r.sent and r.day <= day]:
        sub = svc.sub(rem.subscription_id)
        name = svc.merchant(sub.merchant_id).name if sub else "your subscription"
        await send_alert(svc, user_id=rem.user_id, key=f"chat-reminder:{rem.id}", kind="reminder_note",
                         level="info", title=f"Reminder: {name}", body=rem.note or f"You asked me to remind you "
                         f"about {name} today.", subscription_id=rem.subscription_id)
        async with svc.store.aedit("state") as state:
            next(r for r in state.reminders if r.id == rem.id).sent = True


async def unsent_notice_reminders(svc: Services, day: int) -> None:
    """D7: on the act-by day, a cancelled subscription whose cancellation email is still a draft gets one
    reminder: the terms need written notice, and PayPal's cancel alone doesn't give it."""
    drafts = {n.subscription_id: n for n in svc.store.load("notices").items if n.status == "draft"}
    for timer in [t for t in svc.store.load("timers").items if t.kind == "trial" and t.deadline_day == day]:
        sub, notice = svc.sub(timer.subscription_id), drafts.get(timer.subscription_id)
        if sub is None or notice is None or sub.status != "CANCELLED":
            continue
        await send_alert(svc, user_id=sub.owner_id, key=f"notice-unsent:{sub.id}", kind="notice_unsent",
                         level="warning", title=f"{svc.merchant(sub.merchant_id).name}: email not sent yet",
                         body=(f"Your cancellation email isn't sent yet. The terms need it by "
                               f"{day_text(sub, day + 1)}."),
                         actions=[action("review_email", "Review email", notice_id=notice.id)],
                         subscription_id=sub.id)


async def tick(svc: Services, day: int) -> None:
    await sync_statuses(svc)
    await early_trial_end(svc, day)
    await run_timers(svc, day)
    await unsent_notice_reminders(svc, day)
    await layer2_urgent(svc, day)
    await billing_day(svc, day)
    await scheduled_reminders(svc, day)

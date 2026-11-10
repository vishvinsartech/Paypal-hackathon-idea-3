"""One `tick(day)` = everything SubGuard does on a sim day (Story A and Story B, spec 2 / 7.4).

Order: sync PayPal statuses -> price watch -> early trial end (exports) -> timer warnings -> timer firing ->
Layer 2 urgent checks -> billing-day events (blocked-charge proof) -> renewal reminders for idle honest
subscriptions -> reminders the chat scheduled.
Every alert has an idempotency key, so re-running a day never double-sends.
"""

from __future__ import annotations

import re
import secrets
from decimal import Decimal

from app.core import timers as tm
from app.core.alerts import action, send_alert
from app.core.savings import year_one_cost
from app.core.services import Services
from app.core.usage import exports, last_open_day
from app.integrations.notify import warning_basis
from app.integrations.paypal_gateway import Ctx
from app.integrations.paypal_types import DAYS_PER_UNIT, PayPalError, cycle_days
from app.models import Subscription, Timer
from app.store import utcnow

RENEWAL_NOTICE_DAYS = 3
IDLE_DAYS = 14
UNIT_WORD = {"DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}


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


async def watch_prices(svc: Services) -> None:
    """Diff each active subscription's PayPal plan against its consent snapshot (corner cases 35, 36)."""
    day = svc.day
    for sub in [s for s in svc.store.load("subscriptions").items if s.status == "ACTIVE" and s.consent_snapshot]:
        try:
            plan = await svc.gw.get_plan(sub.plan_id, Ctx(actor="system", user_id=sub.owner_id, subscription_id=sub.id))
        except PayPalError:
            continue
        agreed = sub.consent_snapshot.billing_cycles  # type: ignore[union-attr]
        changes = [(a.price, c.price, c) for a, c in zip(agreed, plan.billing_cycles, strict=False)
                   if a.price != c.price]
        if not changes:
            continue
        old, new, cycle = max(changes, key=lambda x: x[1] - x[0])
        name = svc.merchant(sub.merchant_id).name
        per = UNIT_WORD[cycle.interval_unit]
        if new < old:
            await send_alert(svc, user_id=sub.owner_id, key=f"price-drop:{sub.id}:{new}", kind="price_drop",
                             level="info", title=f"{name} lowered its price to {svc.money(new)}/{per}",
                             body=f"You agreed to {svc.money(old)}/{per}. Nothing to do.", subscription_id=sub.id)
            continue
        await price_rise(svc, sub, old, new, per, year_one_cost(plan.billing_cycles), day)


async def price_rise(svc: Services, sub: Subscription, old: Decimal, new: Decimal, per: str, yearly: Decimal,
                     day: int) -> None:
    name = svc.merchant(sub.merchant_id).name
    user = svc.user(sub.owner_id)
    auto = bool(user and user.settings.auto_cancel_price_rises)
    billing = sub.next_billing_day
    fire_day = billing - 1 if billing is not None else None
    can_auto = auto and fire_day is not None and fire_day >= day + 1
    body = (f"{name} raised its price from {svc.money(old)} to {svc.money(new)}/{per}. You agreed to "
            f"{svc.money(old)}. Keeping it costs {svc.money(yearly)} a year.")
    if can_auto:
        body += f" If you don't answer, I'll cancel it on Day {fire_day}, before the next charge."
    alert, created = await send_alert(
        svc, user_id=sub.owner_id, key=f"price-rise:{sub.id}:{new}", kind="price_rise", level="warning",
        title=f"{name} raised its price to {svc.money(new)}/{per}", body=body, subscription_id=sub.id,
        actions=[action("keep_new_price", f"Keep at {svc.money(new)}", price=str(new)), action("cancel", "Cancel")])
    if not created:
        return
    svc.store.audit.append(actor="system", event="price_rise_detected", user_id=sub.owner_id, subscription_id=sub.id,
                           details={"agreed": str(old), "new": str(new), "per": per, "auto_cancel": can_auto})
    if can_auto and fire_day is not None:
        ok, basis = warning_basis(alert.delivery)
        timer = Timer(id=f"tm-{secrets.token_hex(5)}", subscription_id=sub.id, kind="price_rise", fire_day=fire_day,
                      created_day=day, deadline_day=fire_day, reminder_day=day, billing_day=billing,
                      shown_to_user=alert.delivery.get("in_app") == "shown", warning_delivered=ok,
                      warned_day=day if ok else None, warned_at=utcnow() if ok else None, warning_basis=basis)
        async with svc.store.aedit("timers") as timers:
            timers.items.append(timer)
        svc.store.audit.append(actor="system", event="timer_created", user_id=sub.owner_id, subscription_id=sub.id,
                               rule_id="R2", details={"timer_id": timer.id, "kind": "price_rise",
                                                      "fire_day": fire_day, "warning": basis})


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
                                             url=svc.settings.paypal_autopay_url)],
                             subscription_id=sub.id, cta_url=svc.settings.paypal_autopay_url)


async def billing_day(svc: Services, day: int) -> None:
    for sub in [s for s in svc.store.load("subscriptions").items if s.next_billing_day == day]:
        name = svc.merchant(sub.merchant_id).name
        if sub.status == "CANCELLED":
            await send_alert(svc, user_id=sub.owner_id, key=f"blocked-charge:{sub.id}:{day}", kind="blocked_charge",
                             level="info", title=f"{name}: charge due today was blocked",
                             body="First charge due today: blocked. No active PayPal subscription.",
                             subscription_id=sub.id)
            svc.store.audit.append(actor="system", event="charge_blocked", user_id=sub.owner_id,
                                   subscription_id=sub.id, status_after="CANCELLED",
                                   reason="No active PayPal subscription")
        elif sub.status == "ACTIVE":
            cycles = sub.consent_snapshot.billing_cycles if sub.consent_snapshot else []
            step = next((cycle_days(c) for c in cycles if c.price > 0), DAYS_PER_UNIT["MONTH"])
            async with svc.store.aedit("subscriptions") as subs:
                s = next(x for x in subs.items if x.id == sub.id)
                s.next_billing_day = day + step
            svc.store.audit.append(actor="system", event="charge_due", user_id=sub.owner_id, subscription_id=sub.id,
                                   reason="Billing date reached (simulated; PayPal sandbox time doesn't advance)",
                                   details={"next_billing_day": day + step})


async def renewal_reminders(svc: Services, day: int) -> None:
    """Story B: honest subscriptions get a nudge 3 days before renewal if unused for 2 weeks."""
    pending = {t.subscription_id for t in svc.store.load("timers").items if t.status == "PENDING"}
    for sub in svc.store.load("subscriptions").items:
        if sub.status != "ACTIVE" or sub.id in pending or sub.next_billing_day != day + RENEWAL_NOTICE_DAYS:
            continue
        last = last_open_day(svc.store, sub.owner_id, sub.merchant_id, day)
        idle = day - (last if last is not None else sub.signup_day)
        if idle < IDLE_DAYS:
            continue
        name = svc.merchant(sub.merchant_id).name
        price = sub.consent_snapshot.price if sub.consent_snapshot else Decimal("0")
        weeks = idle // 7
        await send_alert(svc, user_id=sub.owner_id, key=f"renewal:{sub.id}:{sub.next_billing_day}", kind="renewal",
                         level="warning", title=f"{name} renews in {RENEWAL_NOTICE_DAYS} days",
                         body=(f"{name} renews in {RENEWAL_NOTICE_DAYS} days for {svc.money(price)}. You haven't used "
                               f"it for {weeks} week{'s' if weeks != 1 else ''}. Keep or cancel?"),
                         actions=[action("keep", "Keep"), action("cancel", "Cancel")], subscription_id=sub.id)


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


async def tick(svc: Services, day: int) -> None:
    await sync_statuses(svc)
    await watch_prices(svc)
    await early_trial_end(svc, day)
    await run_timers(svc, day)
    await layer2_urgent(svc, day)
    await billing_day(svc, day)
    await renewal_reminders(svc, day)
    await scheduled_reminders(svc, day)

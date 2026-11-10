"""Safety timers (spec 2, rule R2): created + shown at signup, a "keep or cancel?" check-in, fired by the clock.

Keep vs fire race (corner case 10): both claim the timer under the store lock; whoever writes first wins and
the other sees the new state (Keep after firing -> "already cancelled, you won't be charged", corner case 11).
"""

from __future__ import annotations

import secrets

from pydantic import BaseModel

from app.core.actions import DECISION_ACTIONS, cancel_one, confirm_cancelled, layer2_handoff
from app.core.alerts import action, send_alert
from app.core.policy import Decision
from app.core.risk import compute_deadlines
from app.core.services import Services
from app.core.usage import opens_between, times
from app.integrations.notify import warning_basis
from app.models import Review, Subscription, Timer
from app.store import utcnow


def short(name: str) -> str:
    return name.split()[0]


def review_for(svc: Services, sub: Subscription) -> Review | None:
    reviews = [r for r in svc.store.load("reviews").items if r.merchant_id == sub.merchant_id]
    linked = [r for r in reviews if r.subscription_id == sub.id]
    return (linked or sorted(reviews, key=lambda r: r.created_at))[-1] if (linked or reviews) else None


def has_free_trial(sub: Subscription) -> bool:
    cycles = sub.consent_snapshot.billing_cycles if sub.consent_snapshot else []
    return bool(cycles) and cycles[0].price == 0


async def on_registered(svc: Services, sub: Subscription) -> None:
    """Day-0 protection right after approval: a free trial gets a safety timer, shown to the user (R2)."""
    if has_free_trial(sub):
        await create_trial_timer(svc, sub)


async def create_trial_timer(svc: Services, sub: Subscription) -> Timer | None:
    merchant = svc.merchant(sub.merchant_id)
    review = review_for(svc, sub)
    notice = review.data.deadlines.notice_days if review else 0
    if sub.next_billing_day is None:
        return None
    d = compute_deadlines(sub.signup_day, sub.next_billing_day, notice, layer2=not merchant.fair_trial_member)
    if not d.auto_timer_allowed:  # corner case 13: too short to warn 24h ahead
        await send_alert(svc, user_id=sub.owner_id, key=f"decide-now:{sub.id}", kind="decide_now", level="warning",
                         title=f"Decide now about {merchant.name}",
                         body=f"{d.note} The real deadline is Day {d.real_cancel_deadline_day}.",
                         actions=[action("keep", "Keep"), action("cancel", "Cancel")], subscription_id=sub.id)
        svc.store.audit.append(actor="policy", event="timer_not_created", user_id=sub.owner_id, rule_id="R2",
                               subscription_id=sub.id, decision="blocked", reason=d.note)
        return None
    timer = Timer(id=f"tm-{secrets.token_hex(5)}", subscription_id=sub.id, kind="trial", fire_day=d.timer_fire_day,
                  created_day=svc.day, deadline_day=d.real_cancel_deadline_day, reminder_day=d.reminder_day,
                  billing_day=sub.next_billing_day, layer2=d.layer2)
    name = short(merchant.name)
    alert, _ = await send_alert(
        svc, user_id=sub.owner_id, key=f"timer-set:{sub.id}", kind="timer_set", level="info",
        title="I'll check with you before your trial runs out.",
        body=(f"Your real last day to cancel {name} is Day {d.real_cancel_deadline_day}; the first charge is "
              f"Day {d.first_charge_day}. I'll ask you on Day {timer.reminder_day}. If I don't hear back, I'll cancel "
              f"{name} on Day {timer.fire_day} so you're not charged."),
        subscription_id=sub.id)
    timer.shown_to_user = alert.delivery.get("in_app") == "shown"
    async with svc.store.aedit("timers") as timers:
        timers.items.append(timer)
    svc.store.audit.append(actor="system", event="timer_created", user_id=sub.owner_id, subscription_id=sub.id,
                           rule_id="R2", details={"timer_id": timer.id, "kind": "trial", "fire_day": timer.fire_day,
                                                  "deadline_day": timer.deadline_day,
                                                  "reminder_day": timer.reminder_day, "layer2": timer.layer2,
                                                  "shown_to_user": timer.shown_to_user})
    return timer


class KeepResult(BaseModel):
    status: str  # kept | too_late | blocked
    message: str
    actions: list[dict[str, str]] = []


async def keep(svc: Services, user_id: str, sub_id: str) -> KeepResult:
    sub = svc.sub(sub_id)
    if sub is None or sub.owner_id != user_id:
        svc.policy.record(svc.store, Decision(allowed=False, rule_id="R5", subscription_id=sub_id,
                                              reason="You can only act on your own subscriptions"),
                          user_id=user_id, action="keep", requested_by="user")
        return KeepResult(status="blocked", message="That isn't your subscription.")
    kept, fired = [], []
    if sub.status == "ACTIVE":
        await _mark_kept(svc, sub_id)
    async with svc.store.aedit("timers") as timers:
        for t in timers.items:
            if t.subscription_id != sub_id:
                continue
            if t.status == "PENDING":
                t.status, t.note = "KEPT", "user tapped Keep"
                kept.append(t.id)
            elif t.status == "FIRED":
                fired.append(t.id)
    sub = svc.sub(sub_id)
    if not kept and (fired or (sub and sub.status == "CANCELLED")):
        svc.store.audit.append(actor="user", event="keep_too_late", user_id=user_id, subscription_id=sub_id,
                               reason="Timer already fired; subscription is cancelled")
        return KeepResult(status="too_late", message="It's already cancelled, so you won't be charged.")
    svc.store.audit.append(actor="user", event="timer_kept" if kept else "keep_subscription", user_id=user_id,
                           subscription_id=sub_id, details={"timers": kept})
    return KeepResult(status="kept", message="Kept. I won't cancel it or ask again.")


async def _mark_kept(svc: Services, sub_id: str) -> None:
    """Keep = the user decided: remember it and retire any open Keep / Cancel prompts (no further prompts)."""
    async with svc.store.aedit("subscriptions") as subs:
        stored = next(s for s in subs.items if s.id == sub_id)
        stored.kept_day = stored.kept_day if stored.kept_day is not None else svc.day
    async with svc.store.aedit("alerts") as alerts:
        for a in alerts.items:
            offered = {x["action"] for x in a.actions}
            if a.subscription_id == sub_id and a.acknowledged_at is None and offered & DECISION_ACTIONS:
                a.acknowledged_at = utcnow()


async def warn(svc: Services, timer: Timer, day: int) -> None:
    sub = svc.sub(timer.subscription_id)
    if sub is None:
        return
    name = short(svc.merchant(sub.merchant_id).name)
    when = "tomorrow" if timer.fire_day - day == 1 else f"on Day {timer.fire_day}"
    used = opens_between(svc.store, sub.owner_id, sub.merchant_id, sub.signup_day, day)
    deadline = timer.deadline_day or timer.fire_day
    billing = timer.billing_day or sub.next_billing_day
    ends = (f"Your {name} trial ends on Day {billing - 1}, but your real last day to cancel is Day {deadline}."
            if billing is not None else f"Your {name} trial is ending. Your real last day to cancel is Day {deadline}.")
    body = (f"{ends} You've opened it {times(used)}. Do you want to keep it? "
            f"If I don't hear back, I'll cancel it {when} so you're not charged.")
    alert, _ = await send_alert(svc, user_id=sub.owner_id, key=f"timer-warn:{timer.id}:{day}", kind="reminder",
                                level="warning", title=f"{name}: keep it or cancel?", body=body,
                                actions=[action("keep", "Keep"), action("cancel", "Cancel")],
                                subscription_id=sub.id)
    ok, basis = warning_basis(alert.delivery)
    if ok:
        async with svc.store.aedit("timers") as timers:
            t = next(x for x in timers.items if x.id == timer.id)
            t.warning_delivered, t.warned_day, t.warned_at, t.warning_basis = True, day, utcnow(), basis
    svc.store.audit.append(actor="timer", event="timer_warned" if ok else "timer_warning_failed",
                           user_id=sub.owner_id, subscription_id=sub.id, rule_id="R2", result=basis,
                           decision="n/a", details={"timer_id": timer.id, "delivery": alert.delivery})


async def _claim(svc: Services, timer_id: str) -> bool:
    async with svc.store.aedit("timers") as timers:
        t = next(x for x in timers.items if x.id == timer_id)
        if t.status != "PENDING":
            return False
        t.status = "FIRED"
        return True


async def _set_status(svc: Services, timer_id: str, status: str, note: str) -> None:
    async with svc.store.aedit("timers") as timers:
        t = next(x for x in timers.items if x.id == timer_id)
        t.status, t.note = status, note  # type: ignore[assignment]


async def fire(svc: Services, timer: Timer, day: int) -> None:
    sub = svc.sub(timer.subscription_id)
    if sub is None or sub.status != "ACTIVE":
        await _set_status(svc, timer.id, "CANCELLED", f"subscription is {sub.status if sub else 'gone'}")
        return
    merchant = svc.merchant(sub.merchant_id)
    decision = svc.policy.check_timer_fire(svc.store, timer, sub, svc.user(sub.owner_id), day)
    if not decision.allowed:
        billing = timer.billing_day or sub.next_billing_day or day
        if decision.rule_id == "R6" or day >= billing:
            await _set_status(svc, timer.id, "FAILED" if decision.rule_id == "R2" else "CANCELLED", decision.reason)
            await send_alert(svc, user_id=sub.owner_id, key=f"timer-blocked:{timer.id}", kind="urgent",
                             level="urgent", title=f"I couldn't auto-cancel {merchant.name}",
                             body=f"{decision.reason}. Please decide yourself before you're charged.",
                             actions=[action("cancel", "Cancel now"), action("keep", "Keep")], subscription_id=sub.id)
        return  # otherwise stay PENDING: the warning is retried and the timer re-checked next tick
    if not await _claim(svc, timer.id):
        return  # the user tapped Keep first
    svc.store.audit.append(actor="timer", event="timer_fired", user_id=sub.owner_id, subscription_id=sub.id,
                           rule_id="R2", details={"timer_id": timer.id, "kind": timer.kind, "layer2": timer.layer2})
    if timer.layer2 or not merchant.fair_trial_member:
        await layer2_handoff(svc, sub, "Your safety timer fired.")
        return
    result = await cancel_one(svc, sub, actor="timer", rule_id="R2",
                              reason="SubGuard safety timer: trial before first charge", timer_id=timer.id)
    if not result.ok:  # corner case 4: fall back to Layer 2 and alert urgently
        await _set_status(svc, timer.id, "FAILED", result.message)
        await layer2_handoff(svc, sub, f"I couldn't cancel it automatically ({result.message}).")
        return
    await confirm_cancelled(svc, sub, result, by_timer=True)

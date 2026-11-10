"""Priya's dashboard (/user): her story in plain English, built only from the audit log and the store.

Every line comes from a recorded event (R7: nothing is claimed that the log doesn't show). Low-level events
(PayPal HTTP calls, token issue, LLM calls) stay in the full audit log on the live demo page.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.core.audit_log import AuditEntry
from app.core.services import Services

Who = str  # "Priya" | "SubGuard" | "PayPal" | "Safety timer"


class Activity(BaseModel):
    day: int
    seq: int
    who: Who
    kind: str  # css hook: you | guard | paypal | timer | warn
    text: str
    rule_id: str | None = None
    subscription_id: str | None = None


def _d(e: AuditEntry, key: str, default: Any = "") -> Any:
    return e.details.get(key, default)


def _first_up(text: str) -> str:
    return text[:1].upper() + text[1:]


ACTIONS = {"keep": "tapped Keep", "cancel": "tapped Cancel", "review_email": "opened the cancellation email",
           "restart": "chose to restart the trial", "ack": "dismissed an alert", "open_autopay": "opened PayPal"}

# event -> (who, kind, text). Return None to skip an entry.
Describe = Callable[[AuditEntry], tuple[Who, str, str] | None]
EVENTS: dict[str, Describe] = {
    "review_run": lambda e: ("SubGuard", "guard", f"Read the fine print before PayPal: {e.reason}."),
    "prompt_injection_flagged": lambda e: ("SubGuard", "warn", "Found hidden instructions aimed at AI on the "
                                           "merchant page. Ignored them; the score didn't change."),
    "subscription_registered": lambda e: ("Priya", "you", f"Approved the trial in PayPal "
                                          f"(subscription {_d(e, 'paypal_id')}, status {e.status_after})."),
    "consent_snapshot": lambda e: ("SubGuard", "guard", "Saved a consent snapshot of the price and terms she "
                                   "agreed to, from the PayPal plan."),
    "timer_created": lambda e: ("SubGuard", "guard", f"Set a safety timer and showed it to her: check in on Day "
                                f"{_d(e, 'reminder_day', '?')}, cancel on Day "
                                f"{_d(e, 'fire_day', '?')} if she doesn't answer (real deadline Day "
                                f"{_d(e, 'deadline_day', '?')})."),
    "timer_not_created": lambda e: ("SubGuard", "warn", f"No auto-cancel timer: {e.reason}"),
    "timer_warned": lambda e: ("SubGuard", "guard", "Asked her \"Do you want to keep it?\" by email, SMS and in-app."),
    "timer_warning_failed": lambda e: ("SubGuard", "warn", "Couldn't deliver the check-in, so auto-cancel stays off."),
    "alert_action": lambda e: ("Priya", "you", _first_up(ACTIONS.get(_d(e, "action"), f"tapped {_d(e, 'action')}"))
                               + "."),
    "timer_kept": lambda e: ("Priya", "you", "Decided to keep the subscription. SubGuard stopped asking."),
    "keep_subscription": lambda e: ("Priya", "you", "Decided to keep the subscription."),
    "keep_too_late": lambda e: ("Priya", "you", "Tapped Keep after the timer had already cancelled."),
    "chat_message": lambda e: ("Priya", "you", "Asked the SubGuard chat for advice."),
    "timer_fired": lambda e: ("Safety timer", "timer", "No answer by the timer day, so the safety timer fired "
                              "(allowed by rule R2: told on Day 0, warned before)."),
    "paypal_cancel": lambda e: (
        "PayPal", "paypal" if (e.result or "").startswith("ok") else "warn",
        (f"Cancelled the subscription in PayPal ({e.status_before} → {e.status_after}), "
         f"{'after Priya confirmed' if e.actor == 'user' else 'by the safety timer'}.")
        if (e.result or "").startswith("ok") else f"Cancel failed in PayPal ({e.result})."),
    "cancellation_email_drafted": lambda e: ("SubGuard", "guard", f"Drafted the cancellation email her merchant's "
                                             f"terms require ({_d(e, 'drafted_by')}). Waiting for her to send it."),
    "cancellation_email_sent": lambda e: ("Priya", "you", f"Sent the cancellation email (demo outbox, edited: "
                                          f"{'yes' if _d(e, 'edited') else 'no'})."),
    "cancellation_email_gmail_opened": lambda e: ("Priya", "you", f"Opened the cancellation email in Gmail "
                                                  f"(edited: {'yes' if _d(e, 'edited') else 'no'})."),
    "charge_blocked": lambda e: ("PayPal", "paypal", "First charge due: blocked. No active PayPal subscription."),
    "charge_due": lambda e: ("PayPal", "paypal", "Billing date reached; the subscription she kept charges as agreed."),
    "essential_tag": lambda e: ("Priya", "you", f"Marked a subscription as "
                                f"{'essential' if _d(e, 'essential') else 'not essential'}."),
}


def activity_for(svc: Services, user_id: str) -> list[Activity]:
    mine = {s.id for s in svc.store.load("subscriptions").items if s.owner_id == user_id}
    out = []
    for e in svc.store.audit.entries():
        if e.user_id != user_id and e.subscription_id not in mine:
            continue
        if e.event == "paypal_cancel" and e.actor not in ("user", "timer"):
            continue
        describe = EVENTS.get(e.event)
        res = describe(e) if describe else None
        if res is None:
            continue
        who, kind, text = res
        out.append(Activity(day=e.sim_day, seq=e.seq, who=who, kind=kind, text=text, rule_id=e.rule_id,
                            subscription_id=e.subscription_id))
    return out


def usage_by_day(svc: Services, user_id: str) -> list[tuple[int, int]]:
    counts = Counter(u.day for u in svc.store.load("usage").items if u.user_id == user_id and u.kind == "open")
    return sorted(counts.items())

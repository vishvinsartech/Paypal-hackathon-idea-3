"""userA's dashboard (/user), written to her ("you"): her story, built only from the audit log and the store.

Every line comes from a recorded event (R7: nothing is claimed that the log doesn't show). Low-level events
(PayPal HTTP calls, token issue, LLM calls) stay in the full audit log on the live demo page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.core.audit_log import AuditEntry
from app.core.services import Services

Who = str  # "You" | "SubGuard" | "PayPal" | "Safety timer"


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


def _edited(e: AuditEntry) -> str:
    return "yes" if _d(e, "edited") else "no"


def _cancel(e: AuditEntry) -> tuple[Who, str, str]:
    if not (e.result or "").startswith("ok"):
        return "PayPal", "warn", f"Cancel failed in PayPal ({e.result})."
    how = "after you confirmed" if e.actor == "user" else "by your safety timer"
    return "PayPal", "paypal", f"Cancelled your subscription ({e.status_before} → {e.status_after}), {how}."


ACTIONS = {"keep": "you tapped Keep", "cancel": "you tapped Cancel",
           "review_email": "you opened your cancellation email",
           "ack": "you dismissed an alert", "open_autopay": "you opened PayPal"}

# The page is userA's own view (D-110), so it speaks to her: "You" did X, SubGuard did Y for you.
# event -> (who, kind, text). Return None to skip an entry.
Describe = Callable[[AuditEntry], tuple[Who, str, str] | None]
EVENTS: dict[str, Describe] = {
    "review_run": lambda e: ("SubGuard", "guard", f"Read the fine print for you before PayPal: {e.reason}."),
    "prompt_injection_flagged": lambda e: ("SubGuard", "warn", "Found hidden instructions aimed at AI on the "
                                           "merchant page. Ignored them; your risk score didn't change."),
    "subscription_registered": lambda e: ("You", "you", f"You approved the trial in PayPal "
                                          f"(subscription {_d(e, 'paypal_id')}, status {e.status_after})."),
    "consent_snapshot": lambda e: ("SubGuard", "guard", "Saved a snapshot of the price and terms you agreed to, "
                                   "straight from the PayPal plan."),
    "timer_created": lambda e: ("SubGuard", "guard", f"Set a safety timer and told you about it: check in on Day "
                                f"{_d(e, 'reminder_day', '?')}, cancel on Day {_d(e, 'fire_day', '?')} if you don't "
                                f"answer (your real deadline is Day {_d(e, 'deadline_day', '?')})."),
    "timer_not_created": lambda e: ("SubGuard", "warn", f"No auto-cancel timer: {e.reason}"),
    "timer_warned": lambda e: ("SubGuard", "guard", "Asked you \"Do you want to keep it?\" by email, SMS and in-app."),
    "timer_warning_failed": lambda e: ("SubGuard", "warn", "Couldn't reach you with the check-in, so auto-cancel "
                                       "stays off."),
    "alert_action": lambda e: ("You", "you", _first_up(ACTIONS.get(_d(e, "action"), f"you tapped {_d(e, 'action')}"))
                               + "."),
    "timer_kept": lambda e: ("You", "you", "You decided to keep it. SubGuard stopped asking."),
    "keep_subscription": lambda e: ("You", "you", "You decided to keep it."),
    "keep_too_late": lambda e: ("You", "you", "You tapped Keep after the timer had already cancelled."),
    "chat_message": lambda e: ("You", "you", "You asked the SubGuard chat for advice."),
    "timer_fired": lambda e: ("Safety timer", "timer", "You didn't answer, so your safety timer fired "
                              "(allowed by rule R2: you were told on Day 0 and warned before)."),
    "paypal_cancel": _cancel,
    "cancellation_email_drafted": lambda e: ("SubGuard", "guard", f"Drafted the cancellation email the merchant's "
                                             f"terms require ({_d(e, 'drafted_by')}). It waits for you to send it."),
    "cancellation_email_sent": lambda e: ("You", "you", f"You sent the cancellation email (demo outbox, edited: "
                                          f"{_edited(e)})."),
    "cancellation_email_gmail_opened": lambda e: ("You", "you", f"You opened the cancellation email in Gmail "
                                                  f"(edited: {_edited(e)})."),
    "charge_blocked": lambda e: ("PayPal", "paypal", "First charge due: blocked. You have no active PayPal "
                                 "subscription, so nothing was taken."),
    "charge_due": lambda e: ("PayPal", "paypal", "Billing date reached; the subscription you kept charges as agreed."),
    "essential_tag": lambda e: ("You", "you", f"You marked a subscription as "
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

"""Priya's dashboard (/user), written to her ("you"): her story, built only from the audit log and the store.

Every line comes from a recorded event (R7: nothing is claimed that the log doesn't show). Low-level events
(PayPal HTTP calls, token issue, LLM calls) stay in the full audit log on the live demo page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.core.audit_log import AuditEntry
from app.core.services import Services
from app.core.sub_dates import day_text
from app.models import Subscription

Who = str  # "You" | "SubGuard" | "PayPal" | "Safety timer"


class Activity(BaseModel):
    day: int
    seq: int
    who: Who
    kind: str  # css hook: you | guard | paypal | timer | warn
    text: str
    rule_id: str | None = None
    subscription_id: str | None = None
    short: str = ""  # D-169: the few words "What SubGuard did" shows on the Overview


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

# The page is Priya's own view (D-110), so it speaks to her: "You" did X, SubGuard did Y for you.
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
    "cancellation_email_drafted": lambda e: ("SubGuard", "guard", "Drafted the cancellation email the merchant's "
                                             "terms require. It waits for you to send it."),  # U4: no "mock" label
    "cancellation_email_sent": lambda e: ("You", "you", f"You sent the cancellation email (demo outbox, edited: "
                                          f"{_edited(e)})."),
    "cancellation_email_app_opened": lambda e: ("You", "you", f"You opened the cancellation email in your email "
                                                f"app (edited: {_edited(e)})."),
    "cancellation_email_gmail_opened": lambda e: ("You", "you", f"You opened the cancellation email in webmail "
                                                  f"(edited: {_edited(e)})."),
    "notice_auto_sent": lambda e: ("SubGuard", "guard", "Sent your cancellation email for you, as you asked at "
                                   "sign-up (demo outbox)."),
    "charge_blocked": lambda e: ("SubGuard", "guard", e.reason or "Checked PayPal: no active subscription, so no "
                                 "charge can be taken."),
    "charge_due": lambda e: ("PayPal", "paypal", "Billing date reached; the subscription you kept charges as agreed."),
    "essential_tag": lambda e: ("You", "you", f"You marked a subscription as "
                                f"{'essential' if _d(e, 'essential') else 'not essential'}."),
}


def _short_cancel(e: AuditEntry) -> str:
    if not (e.result or "").startswith("ok"):
        return "Cancel failed in PayPal"
    return "Cancelled in PayPal"


# D-169: the Overview's "What SubGuard did" lines: a few words each, no ids, no "(demo outbox, edited: no)".
SHORT: dict[str, Callable[[AuditEntry], str]] = {
    "review_run": lambda e: "Read the fine print before PayPal",
    "prompt_injection_flagged": lambda e: "Ignored hidden instructions on the page",
    "subscription_registered": lambda e: "You started the trial in PayPal",
    "consent_snapshot": lambda e: "Saved the price you agreed to",
    "timer_created": lambda e: "Set a safety timer",
    "timer_not_created": lambda e: "No safety timer for this one",
    "timer_warned": lambda e: "Asked you: keep or cancel?",
    "timer_warning_failed": lambda e: "Couldn't reach you, so no auto-cancel",
    "alert_action": lambda e: {"keep": "You chose Keep", "cancel": "You chose Cancel",
                               "review_email": "You opened your email", "open_autopay": "You opened PayPal"}
    .get(_d(e, "action"), "You answered an alert"),
    "timer_kept": lambda e: "You kept it",
    "keep_subscription": lambda e: "You kept it",
    "keep_too_late": lambda e: "Keep came after the cancel",
    "timer_fired": lambda e: "No answer, so the safety timer acted (R2)",
    "paypal_cancel": _short_cancel,
    "cancellation_email_drafted": lambda e: "Drafted your cancellation email",
    "cancellation_email_sent": lambda e: "Cancellation email sent",
    "cancellation_email_app_opened": lambda e: "Email opened in your email app",
    "cancellation_email_gmail_opened": lambda e: "Email opened in webmail",
    "notice_auto_sent": lambda e: "Sent your cancellation email for you",
    "charge_blocked": lambda e: "First charge blocked: nothing to charge",
    "charge_due": lambda e: "First charge taken, as you agreed",
    "essential_tag": lambda e: "You marked it essential" if _d(e, "essential") else "You unmarked essential",
}

def _timer_text(e: AuditEntry, sub: Subscription) -> str:
    """timer_created with calendar dates (B2): "check in on Nov 16, cancel on Nov 17 if you don't answer"."""
    def on(key: str) -> str:
        day = _d(e, key, None)
        return day_text(sub, int(day)) if isinstance(day, int) else "?"
    if _d(e, "auto_cancel", True) is False:  # D-177: Settings had auto-cancel off
        return (f"Set a check-in and told you about it: check in on {on('reminder_day')}; auto-cancel is off, so "
                f"you decide (act by {on('deadline_day')}).")
    return (f"Set a safety timer and told you about it: check in on {on('reminder_day')}, cancel on {on('fire_day')} "
            f"if you don't answer (act by {on('deadline_day')}).")


def activity_for(svc: Services, user_id: str) -> list[Activity]:
    subs = {s.id: s for s in svc.store.load("subscriptions").items}
    mine = {sid for sid, s in subs.items() if s.owner_id == user_id}
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
        if e.event == "timer_created" and (sub := subs.get(e.subscription_id or "")) is not None:
            text = _timer_text(e, sub)
        brief = SHORT.get(e.event)
        out.append(Activity(day=e.sim_day, seq=e.seq, who=who, kind=kind, text=text, rule_id=e.rule_id,
                            subscription_id=e.subscription_id, short=brief(e) if brief else text))
    return out

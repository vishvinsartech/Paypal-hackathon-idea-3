"""B4: the live demo's 7-step tracker, derived from the subscription's audit events (not set by Start demo).

So clicking through by hand (shop -> Day buttons -> Keep / Cancel) ticks the same steps as Start demo does.
Steps: read -> approve -> timer -> wait -> ask -> outcome -> proof. Each: state (pending | active | done | warn |
skipped) and a short detail. Dates are calendar dates for this subscription (sub_dates.day_text), never LLM.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.audit_log import AuditEntry
from app.core.services import Services
from app.core.sub_dates import day_text
from app.models import Subscription

STEP_KEYS = ("read", "approve", "timer", "wait", "ask", "outcome", "proof")


class Step(BaseModel):
    key: str
    state: str = "pending"
    detail: str | None = None  # None: keep the template's hint


def _first(entries: list[AuditEntry], event: str) -> AuditEntry | None:
    return next((e for e in entries if e.event == event), None)


def derive_steps(svc: Services, sub: Subscription | None, entries: list[AuditEntry],
                 review_entry: AuditEntry | None) -> list[Step]:
    """`entries`: this subscription's audit entries in order; `review_entry`: the review_run that preceded it."""
    steps = {k: Step(key=k) for k in STEP_KEYS}
    if sub is None:
        return list(steps.values())
    today = svc.day
    if review_entry is not None:
        d = review_entry.details
        act_by = d.get("deadline_day")
        steps["read"] = Step(key="read", state="done", detail=f"Risk {d.get('risk')}"
                             + (f" · act by {day_text(sub, act_by)}" if act_by is not None else ""))
    steps["approve"] = Step(key="approve", state="done", detail="PayPal ACTIVE")

    created, refused = _first(entries, "timer_created"), _first(entries, "timer_not_created")
    reminder = fire = None
    if created is not None:
        reminder, fire = created.details.get("reminder_day"), created.details.get("fire_day")
        steps["timer"] = Step(key="timer", state="done", detail=f"Ask {day_text(sub, reminder)} · cancel "
                              f"{day_text(sub, fire)}" if reminder is not None and fire is not None else None)
    elif refused is not None:
        steps["timer"] = Step(key="timer", state="warn", detail="No auto-timer")

    decided_day = sub.cancelled_day if sub.cancelled_day is not None else sub.kept_day
    end = decided_day if decided_day is not None else today
    if reminder is not None and end >= reminder:
        steps["wait"] = Step(key="wait", state="done", detail=f"{reminder - sub.signup_day} days")
    elif today > sub.signup_day:
        steps["wait"] = Step(key="wait", state="active" if decided_day is None else "done",
                             detail=f"{end - sub.signup_day} day{'s' if end - sub.signup_day != 1 else ''} in")

    warned = _first(entries, "timer_warned")
    if warned is not None:
        steps["ask"] = Step(key="ask", state="done", detail=f"Asked {day_text(sub, warned.sim_day)}")
    elif decided_day is not None:
        steps["ask"] = Step(key="ask", state="skipped", detail="she decided first")

    if sub.cancelled_day is not None:
        when = day_text(sub, sub.cancelled_day)
        text = {"user": f"Cancelled {when}", "timer": f"Auto-cancelled {when} (R2)"}.get(
            sub.cancelled_by or "", f"Cancelled outside SubGuard {when}")
        steps["outcome"] = Step(key="outcome", state="done", detail=text)
    elif sub.kept_day is not None:
        steps["outcome"] = Step(key="outcome", state="done", detail="Kept")
    elif warned is not None:
        steps["outcome"] = Step(key="outcome", state="active", detail="waiting for Priya")

    blocked, charged = _first(entries, "charge_blocked"), _first(entries, "charge_due")
    if blocked is not None:
        ok = blocked.result in (None, "no_active_subscription")
        steps["proof"] = Step(key="proof", state="done" if ok else "warn",
                              detail="Checked PayPal: no charge" if ok else "check PayPal")
    elif charged is not None:
        steps["proof"] = Step(key="proof", state="warn", detail=f"{day_text(sub, charged.sim_day)}: charged")
    return list(steps.values())

"""Activity timeline types and day grouping (D-172); the builder is in timeline.py."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.services import Services
from app.core.sub_dates import cal
from app.store import utcnow

Actor = Literal["you", "subguard", "paypal", "merchant"]
MAX_TEXT = 70
CHANNELS = {"in_app": "App", "email": "Email", "sms": "SMS"}
DELIVERED = {"shown", "accepted", "mocked", "sent", "ok"}
FOLDED = {"timer_set", "cancelled", "blocked_charge"}  # these messages restate an event: they join its entry
ASKS = {"reminder", "decide_now", "urgent", "action_needed"}  # one per subscription (no repeated check-ins)
RULES = {
    "R1": "You confirmed it yourself with a one-time tap. SubGuard never cancels on its own say-so (rule R1).",
    "R2": "Safety timer (rule R2): shown to you at sign-up, asked you at least a day before, and acts only "
          "before the first charge.",
    "R7": "SubGuard only says this because PayPal confirmed it (rule R7).",
}
QUOTE_FIRST = ("NOTICE_PERIOD", "EARLY_TRIAL_TERMINATION", "AUTO_RENEW", "INTRO_PRICE_STEP_UP")


class ProofRow(BaseModel):
    label: str
    value: str
    quote: bool = False


class Entry(BaseModel):
    key: str
    kind: str  # data-kind hook for checks
    day: int
    seq: int
    actor: Actor
    actor_label: str
    text: str
    detail: str = ""
    answer: str = ""  # "You chose: Cancel"
    mark: Literal["", "done", "ask"] = ""
    email_id: str | None = None
    email_label: str = "View email"
    proof: list[ProofRow] = Field(default_factory=list)
    subscription_id: str | None = None


def fit(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


def channels(delivery: dict[str, str]) -> str:
    """ "App · Email": only the channels that delivered; channels that aren't set up are left out (no ✗)."""
    return " · ".join(CHANNELS.get(k, k) for k, v in delivery.items() if v in DELIVERED)


def run_day0(svc: Services) -> datetime:
    """The run's Day 0 on the calendar (D-172); before the first sign-up, today is the current sim day."""
    return svc.store.load("state").day0_at or utcnow() - timedelta(days=svc.day)


def by_day(svc: Services, entries: list[Entry]) -> list[dict[str, Any]]:
    """Entries grouped by calendar day, newest day first. Labels: "Today · Nov 17" or "Tue · Nov 17"."""
    day0 = run_day0(svc)
    groups: list[dict[str, Any]] = []
    for entry in entries:
        if not groups or groups[-1]["day"] != entry.day:
            at = day0 + timedelta(days=entry.day)
            label = f"{'Today' if entry.day == svc.day else f'{at:%a}'} · {cal(at)}"
            groups.append({"day": entry.day, "label": label, "iso": at.date().isoformat(), "entries": []})
        groups[-1]["entries"].append(entry)
    return groups


def date_label(svc: Services, day: int) -> str:
    return cal(run_day0(svc) + timedelta(days=day))

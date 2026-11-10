"""Key dates on userA's subscription card (D-115): every "Day N" also as a calendar date.

The sign-up moment is real: `registered_at`, the date and time SubGuard recorded the PayPal approval. Every
later milestone is a sim day, mapped to a date as `registered_at + (N - signup_day)` days, so "Day 7" reads as
the date that is 7 days after you subscribed. Pages show the dates in the viewer's own time zone (user.js
localizes the <time> tags); the server text is a UTC fallback. Code computes every date; nothing here is LLM.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.services import Services
from app.models import Subscription, Timer

UTC_DATE = "%a %d %b %Y"
UTC_DATETIME = "%a %d %b %Y, %H:%M UTC"


def date_of_day(sub: Subscription, day: int) -> datetime | None:
    """The calendar moment of sim day `day` for this subscription (None if its sign-up time wasn't recorded)."""
    if sub.registered_at is None:
        return None
    return sub.registered_at + timedelta(days=day - sub.signup_day)


def stamp(at: datetime | None, *, with_time: bool) -> dict[str, Any] | None:
    """A <time> tag's data: ISO for the browser, plus a UTC fallback text."""
    if at is None:
        return None
    return {"iso": at.isoformat(), "fmt": "datetime" if with_time else "date",
            "text": at.strftime(UTC_DATETIME if with_time else UTC_DATE)}


def _row(sub: Subscription, key: str, label: str, day: int | None, state: str, note: str = "",
         at: datetime | None = None, with_time: bool = False) -> dict[str, Any] | None:
    if day is None:
        return None
    return {"key": key, "label": label, "day": day, "state": state, "note": note,
            "when": stamp(at or date_of_day(sub, day), with_time=with_time)}


def _when(day: int, today: int) -> str:
    if day == today:
        return "today"
    return "done" if day < today else "upcoming"


def _days_left(day: int, today: int) -> str:
    left = day - today
    return "Today" if left == 0 else ("Passed" if left < 0 else f"{left} day{'s' if left != 1 else ''} left")


def _cancel_moment(sub: Subscription) -> datetime | None:
    """Cancel date = the sim day it happened, with the real time of day of the PayPal cancel."""
    base = date_of_day(sub, sub.cancelled_day) if sub.cancelled_day is not None else None
    if base is None or sub.cancelled_at is None:
        return base
    return base.replace(hour=sub.cancelled_at.hour, minute=sub.cancelled_at.minute, second=sub.cancelled_at.second)


def key_dates(svc: Services, sub: Subscription, view: dict[str, Any], timer: Timer | None,
              deadline_day: int | None) -> list[dict[str, Any]]:
    """Subscribed -> check-in -> real last day to cancel -> auto-cancel -> trial ends -> first charge -> price
    rise, plus Cancelled / Kept. Each row: label, sim day, calendar date, state (done|today|upcoming|off|
    blocked) and a short note."""
    today, active = svc.day, sub.status == "ACTIVE"
    cancelled, kept = sub.cancelled_day is not None, sub.kept_day is not None
    rows = [_row(sub, "subscribed", "Subscribed", sub.signup_day, "done", "Approved in PayPal",
                 at=sub.registered_at, with_time=True)]
    if timer and timer.kind == "trial":
        reminder = timer.reminder_day
        if reminder is not None:
            state = _when(reminder, today) if active or reminder <= (sub.cancelled_day or today) else "off"
            rows.append(_row(sub, "check_in", "SubGuard checks in with you", reminder, state,
                             "Email, SMS and in-app" if state != "off" else "Not needed"))
        if deadline_day is not None:
            met = cancelled and sub.cancelled_day is not None and sub.cancelled_day <= deadline_day
            note = "Cancelled in time ✓" if met else ("You kept it" if kept else _days_left(deadline_day, today))
            rows.append(_row(sub, "deadline", "Real last day to cancel", deadline_day,
                             "done" if met or kept else _when(deadline_day, today), note))
        timer_note, timer_state = {
            "PENDING": ("Cancels in PayPal unless you tap Keep", _when(timer.fire_day, today)),
            "FIRED": ("Cancelled by your safety timer", "done"),
            "KEPT": ("Off: you kept it", "off"),
            "CANCELLED": ("Not needed: you cancelled", "off"),
            "FAILED": ("Failed: needs you", "today"),
        }[timer.status]
        rows.append(_row(sub, "auto_cancel", "Auto-cancel (safety timer)", timer.fire_day, timer_state, timer_note))
    rows.append(_row(sub, "trial_end", "Free trial ends (site says)", view.get("trial_end_day"),
                     _when(view["trial_end_day"], today) if view.get("trial_end_day") is not None else "upcoming"))
    if sub.next_billing_day is not None:
        price = view["next_charge_text"].split(" · ")[-1] if active and " · " in view["next_charge_text"] else ""
        blocked = not active
        rows.append(_row(sub, "first_charge", "First charge", sub.next_billing_day,
                         "blocked" if blocked else _when(sub.next_billing_day, today),
                         "Blocked: no active PayPal subscription" if blocked else price))
    if active and view.get("step_up_day") is not None:
        rows.append(_row(sub, "step_up", "Price goes up", view["step_up_day"], "upcoming",
                         f"to {view['step_up_text']}" if view.get("step_up_text") else ""))
    if cancelled:
        by = "by you" if sub.cancelled_by == "user" else ("by your safety timer" if sub.cancelled_by == "timer"
                                                          else "outside SubGuard")
        rows.append(_row(sub, "cancelled", "Cancelled in PayPal", sub.cancelled_day, "done", by,
                         at=_cancel_moment(sub), with_time=sub.cancelled_at is not None))
    elif kept:
        rows.append(_row(sub, "kept", "You kept it", sub.kept_day, "done", "SubGuard stopped asking"))
    out = [r for r in rows if r is not None]
    return sorted(out, key=lambda r: (r["day"], r["key"] in ("cancelled", "kept")))

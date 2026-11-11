"""Usage numbers from usage.json (opening the fake app page records an event). Only days <= today count."""

from __future__ import annotations

from app.models import UsageEvent
from app.store import JsonStore


def _events(store: JsonStore, user_id: str, merchant_id: str, today: int, kind: str = "open") -> list[UsageEvent]:
    return [e for e in store.load("usage").items
            if e.user_id == user_id and e.merchant_id == merchant_id and e.kind == kind and e.day <= today]


def opens_between(store: JsonStore, user_id: str, merchant_id: str, first_day: int, today: int) -> int:
    return sum(1 for e in _events(store, user_id, merchant_id, today) if e.day >= first_day)


def days_used(store: JsonStore, user_id: str, merchant_id: str, window: int, today: int) -> int:
    """Distinct days with an open in the last `window` days (today included)."""
    return len({e.day for e in _events(store, user_id, merchant_id, today) if e.day > today - window})


def last_open_day(store: JsonStore, user_id: str, merchant_id: str, today: int) -> int | None:
    days = [e.day for e in _events(store, user_id, merchant_id, today)]
    return max(days) if days else None


def exports(store: JsonStore, user_id: str, merchant_id: str, since_day: int, today: int) -> int:
    return sum(1 for e in _events(store, user_id, merchant_id, today, "export") if e.day >= since_day)


def times(n: int) -> str:
    return {0: "never", 1: "once", 2: "twice"}.get(n, f"{n} times")


SIMULATED_SOURCE = "from {name}'s app activity, simulated in this demo"


def usage_label(n: int, merchant_short: str) -> str:
    """D8: usage stated with its source: "opened it twice (from Penwright's app activity, simulated in this demo)"."""
    return f"opened it {times(n)} ({SIMULATED_SOURCE.format(name=merchant_short)})"

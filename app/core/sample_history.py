"""Priya's sample history (D-174): three fictional subscriptions from `data/seed/sample_history.json`.

Read-only. They are never in PayPal, never in `data/runtime/`, and no policy, timer or PayPal code sees them, so
Start demo and Reset can't change them. Pages label them "Sample history". Money is Decimal; dates are real
calendar dates, except "last used", which is relative to the demo's today.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SampleSub(BaseModel):
    id: str
    owner_id: str = "priya"  # R5: only Priya's page shows them
    merchant: str
    category: str = ""
    plan: str
    currency: str = "USD"
    price: Decimal
    new_price: Decimal | None = None
    status: Literal["ACTIVE", "CANCELLED"]
    kind: Literal["paid", "trial"]
    risk: int = Field(ge=0, le=100)
    terms_note: str = ""
    started: date
    billing_day: int | None = Field(None, ge=1, le=28)
    last_used: date | None = None
    last_used_days_ago: int | None = None
    ended: date | None = None
    ended_how: str = ""
    saved: Decimal | None = None
    saved_per: str = ""
    saved_kind: Literal["trial", "price_rise"] | None = None

    def used_on(self, today: date) -> date | None:
        if self.last_used_days_ago is not None:
            return today - timedelta(days=self.last_used_days_ago)
        return self.last_used

    def charge_dates(self, until: date) -> list[date]:
        """Monthly charges on `billing_day` from the start, before it ended (exclusive) and up to `until`."""
        if self.kind != "paid" or self.billing_day is None:
            return []
        stop = min(until, self.ended - timedelta(days=1)) if self.ended else until
        out, d = [], _month_day(self.started.year, self.started.month, self.billing_day)
        if d < self.started:
            d = _next_month(d, self.billing_day)
        while d <= stop:
            out.append(d)
            d = _next_month(d, self.billing_day)
        return out

    def next_charges(self, today: date, n: int) -> list[date]:
        """The next `n` charges after today (only while it's in use)."""
        if self.status != "ACTIVE" or self.billing_day is None:
            return []
        d = _month_day(today.year, today.month, self.billing_day)
        if d <= today:
            d = _next_month(d, self.billing_day)
        out = []
        for _ in range(n):
            out.append(d)
            d = _next_month(d, self.billing_day)
        return out


class SampleList(BaseModel):
    items: list[SampleSub] = Field(default_factory=list)


def _month_day(year: int, month: int, day: int) -> date:
    return date(year, month, day)


def _next_month(d: date, day: int) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, day)


@lru_cache(maxsize=4)
def _load(path: Path, mtime: float) -> tuple[SampleSub, ...]:
    return tuple(SampleList.model_validate_json(path.read_text(encoding="utf-8")).items)


def samples(seed_dir: Path, user_id: str) -> list[SampleSub]:
    """This user's sample subscriptions (empty if the file is missing). Cached until the file changes."""
    path = seed_dir / "sample_history.json"
    if not path.exists():
        return []
    return [s for s in _load(path, path.stat().st_mtime) if s.owner_id == user_id]

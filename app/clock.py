"""Simulated clock (spec 7.4): `sim_day` in state.json; advancing runs tick() once per day crossed, in order.

Idempotent: a day is ticked at most once (`last_tick_day`), and alerts carry idempotency keys, so jumping
0 -> 21 never double-sends (corner case 14). The sim clock drives SubGuard; PayPal sandbox time doesn't move.
"""

from __future__ import annotations

from app.core.escalation import tick
from app.core.services import Services
from app.store import utcnow


async def advance(svc: Services, days: int = 1, *, to_day: int | None = None) -> int:
    start = svc.day
    target = to_day if to_day is not None else start + max(0, days)
    for day in range(start + 1, target + 1):
        async with svc.store.aedit("state") as state:
            state.sim_day = day
            already = state.last_tick_day is not None and state.last_tick_day >= day
        if not already:
            await tick(svc, day)
            async with svc.store.aedit("state") as state:
                state.last_tick_day, state.last_tick_at = day, utcnow()
    if target > start:
        svc.store.audit.append(actor="system", event="clock_advanced", details={"from": start, "to": target})
    return svc.day

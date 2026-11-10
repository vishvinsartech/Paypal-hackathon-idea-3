"""Mock-mode demo data (DEMO_SEED=true): Priya's scripted Penwright usage.

The story starts with no subscriptions: Priya approves the Penwright trial herself on Day 0. Usage events are
scripted (`source="seed"`) so the Day 5 check-in can say "You've opened it twice" reproducibly (D-053).
Only days <= today count, so future-dated events "happen" as the clock advances; the subscription id is
left empty because usage is matched by user + merchant.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.services import Services
from app.models import UsageEvent
from app.store import utcnow

SCRIPTED_USAGE = {("priya", "penwright"): [2, 4]}

ReviewFn = Callable[[str, str, str, int], Awaitable[str | None]]  # (merchant, plan_key, user, day) -> review id


async def seed_demo(svc: Services, review: ReviewFn | None = None) -> bool:
    """`review` is accepted for API compatibility (the reset route passes one); no seeded subscription needs it."""
    if svc.gw.mock is None or not svc.settings.demo_seed or svc.store.load("state").demo_seeded:
        return False
    async with svc.store.aedit("usage") as usage:
        for (user_id, merchant_id), days in SCRIPTED_USAGE.items():
            usage.items += [UsageEvent(user_id=user_id, merchant_id=merchant_id, subscription_id=None, day=d,
                                       at=utcnow(), source="seed") for d in days]
    async with svc.store.aedit("state") as state:
        state.demo_seeded = True
    svc.store.audit.append(actor="system", event="demo_seeded", reason="Demo data: Priya's Penwright usage",
                           details={"usage": {f"{u}:{m}": d for (u, m), d in SCRIPTED_USAGE.items()}})
    return True

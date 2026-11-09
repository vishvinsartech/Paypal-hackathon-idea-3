"""Mock-mode demo data (DEMO_SEED=true): Priya already pays for Framewise; John subscribed to Lumen Notes on Day 0.

Usage events are scripted (`source="seed"`) so the story's numbers are reproducible (D-053): Priya opened
Framewise 3 times this month and Penwright twice during the trial; John used Lumen on Days 1-9 and 12.
Only days <= today count, so future-dated events "happen" as the clock advances.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.services import Services
from app.core.signup import register_active
from app.integrations.paypal_gateway import Ctx
from app.models import UsageEvent
from app.store import utcnow

SCRIPTED_USAGE = {("priya", "framewise"): [-2, 3, 10], ("priya", "penwright"): [2, 4],
                  ("john", "lumen"): [*range(1, 10), 12]}
SEEDED = [("priya", "framewise", "framewise-basic", -5), ("john", "lumen", "lumen-monthly", 0)]

ReviewFn = Callable[[str, str, str, int], Awaitable[str | None]]  # (merchant, plan_key, user, day) -> review id


async def seed_demo(svc: Services, review: ReviewFn | None = None) -> bool:
    if svc.gw.mock is None or not svc.settings.demo_seed or svc.store.load("state").demo_seeded:
        return False
    for user_id, merchant_id, plan_key, signup_day in SEEDED:
        ctx = Ctx(actor="system", user_id=user_id, merchant=svc.merchant(merchant_id))
        created = await svc.gw.create_subscription(svc.gw.plan_id(plan_key), ctx)
        view = await svc.gw.mock_approve(created.id, ctx)
        review_id = await review(merchant_id, plan_key, user_id, signup_day) if review else None
        await register_active(svc, view, merchant_id=merchant_id, plan_key=plan_key, user_id=user_id,
                              review_id=review_id, signup_day=signup_day)
    subs = svc.store.load("subscriptions").items
    async with svc.store.aedit("usage") as usage:
        for (user_id, merchant_id), days in SCRIPTED_USAGE.items():
            sub = next((s for s in subs if s.owner_id == user_id and s.merchant_id == merchant_id), None)
            sid = sub.id if sub else None
            usage.items += [UsageEvent(user_id=user_id, merchant_id=merchant_id, subscription_id=sid, day=d,
                                       at=utcnow(), source="seed") for d in days]
    async with svc.store.aedit("state") as state:
        state.demo_seeded = True
    svc.store.audit.append(actor="system", event="demo_seeded", reason="Demo data: Priya/Framewise, John/Lumen",
                           details={"subscriptions": [f"{u}:{p}" for u, _, p, _ in SEEDED]})
    return True

"""Shared helpers for review tests: captures from the real shop pages, plans, auditors, stub providers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal

from app.config import ROOT_DIR, Settings
from app.core.auditor import Auditor
from app.integrations.capture import PageCapture, StaticCapture
from app.integrations.paypal_types import PlanView
from app.llm.base import ChatMessage, ChatTurn, LLMError, parse_review_json
from app.llm.mock_provider import MockProvider
from app.llm.tools_schema import ToolSpec
from app.main import create_app
from app.models import BillingCycleDef, Merchant
from app.pricing import Pricing
from app.review_types import ReviewData, ReviewResult
from app.store import JsonStore

FIXTURES = ROOT_DIR / "data" / "fixtures" / "llm"


def capture_page(settings: Settings, path: str) -> PageCapture:
    app = create_app(settings)
    return asyncio.run(StaticCapture(app, ROOT_DIR / "shop" / "static" / "shop.css").capture(path))


def plan_for(key: str, pricing: Pricing | None = None, price_override: Decimal | None = None) -> PlanView:
    pricing = pricing or Pricing()
    merchant_id = key.split("-")[0]
    plan = next(p for p in pricing.plans_for(merchant_id) if p.key == key)
    cycles = [c.model_copy() for c in plan.billing_cycles]
    if price_override is not None:
        cycles[-1] = BillingCycleDef(**{**cycles[-1].model_dump(), "price": price_override})
    return PlanView(id=f"P-{key}", name=plan.name, currency=plan.currency, billing_cycles=cycles)


def merchant(store: JsonStore, merchant_id: str, fair_trial: bool = True) -> Merchant:
    m = next(x for x in store.load("merchants").items if x.id == merchant_id)
    return m.model_copy(update={"fair_trial_member": fair_trial})


def mock_text(merchant_id: str) -> str:
    return MockProvider(FIXTURES, Pricing()).review_fixture_text(merchant_id)


def auditor(store: JsonStore, provider: object, timeout: float = 5.0) -> Auditor:
    return Auditor(provider, store, store.seed_dir / "dark_patterns.json", timeout)  # type: ignore[arg-type]


def run_review(store: JsonStore, provider: object, capture: PageCapture, key: str, *, fair_trial: bool = True,
               plan: PlanView | None = None, timeout: float = 5.0) -> ReviewData:
    plan = plan or plan_for(key)
    return asyncio.run(auditor(store, provider, timeout).review(
        capture, plan, merchant=merchant(store, key.split("-")[0], fair_trial), plan_key=key, signup_day=0,
        user_id="priya"))


class ScriptedProvider:
    """Returns each scripted answer in turn: a JSON string, an Exception, or a callable producing either."""

    name = "stub"
    model = "stub-model"

    def __init__(self, *answers: str | Exception | Callable[[], object]) -> None:
        self.answers = list(answers)
        self.feedbacks: list[str | None] = []

    async def extract_findings(self, capture: PageCapture, *, feedback: str | None = None) -> ReviewResult:
        self.feedbacks.append(feedback)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if callable(answer):
            answer = answer()
            if asyncio.iscoroutine(answer):
                answer = await answer
        if isinstance(answer, Exception):
            raise answer
        return parse_review_json(str(answer), {})

    async def chat_step(self, messages: list[ChatMessage], tools: list[ToolSpec], **_: object) -> ChatTurn:
        raise LLMError("not scripted")

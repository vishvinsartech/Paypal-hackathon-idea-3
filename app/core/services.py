"""The app's long-lived collaborators, passed together to the core logic (policy, timers, escalation)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.core.policy import Policy
from app.integrations.notify import Notifier
from app.integrations.paypal_gateway import PayPalGateway
from app.llm.base import LLMProvider
from app.models import Merchant, Subscription, User
from app.store import JsonStore


@dataclass
class Services:
    settings: Settings
    store: JsonStore
    gw: PayPalGateway
    notifier: Notifier
    policy: Policy = field(default_factory=Policy)
    llm: LLMProvider | None = None  # drafts the cancellation email (falls back to a template without it)

    @property
    def day(self) -> int:
        return self.store.load("state").sim_day

    def merchant(self, merchant_id: str) -> Merchant:
        return next(m for m in self.store.load("merchants").items if m.id == merchant_id)

    def user(self, user_id: str) -> User | None:
        return next((u for u in self.store.load("users").items if u.id == user_id), None)

    def sub(self, sub_id: str) -> Subscription | None:
        return next((s for s in self.store.load("subscriptions").items if s.id == sub_id), None)

    def money(self, amount: object) -> str:
        return self.settings.pricing.money(str(amount))

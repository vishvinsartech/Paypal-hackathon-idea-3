"""Mock PayPal: the subscription state machine, persisted in data/runtime/mock_paypal.json.

Same method signatures as the SDK backend. APPROVAL_PENDING -> ACTIVE -> CANCELLED (+ SUSPENDED / EXPIRED
for display). Cancelling a subscription that isn't ACTIVE/SUSPENDED answers 422 SUBSCRIPTION_STATUS_INVALID,
like real PayPal. `inject_failure()` simulates errors for the corner-case tests (`?fail=cancel`).
"""

from __future__ import annotations

import secrets
from decimal import Decimal

from app.integrations.paypal_types import PayPalError, PlanView, SubscriptionView
from app.models import Merchant, MockPayPalState, MockPlan, MockSub
from app.store import JsonStore, utcnow

MOCK_PLAN_PREFIX = "P-MOCK-"


def mock_plan_id(plan_key: str) -> str:
    return MOCK_PLAN_PREFIX + plan_key.upper().replace("-", "_")


class MockPayPal:
    transport = "mock"

    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self._failures: dict[str, list[int | None]] = {}

    # ---- test hooks ---------------------------------------------------------
    def inject_failure(self, op: str, status: int | None = 503, times: int = 1) -> None:
        """Next `times` calls of `op` fail with `status` (None = no response / network error)."""
        self._failures.setdefault(op, []).extend([status] * times)

    def _maybe_fail(self, op: str) -> None:
        queue = self._failures.get(op)
        if queue:
            status = queue.pop(0)
            raise PayPalError(
                f"simulated {op} failure", status=status, name="SIMULATED_FAILURE",
                debug_id=f"mock-{secrets.token_hex(4)}", transport="mock",
                retryable=status is None or status >= 500 or status in (401, 408, 429),
            )

    # ---- state --------------------------------------------------------------
    def _ensure_plans(self, state: MockPayPalState) -> None:
        if state.plans:
            return
        for merchant in self.store.load("merchants").items:
            for plan in merchant.plans:
                pid = mock_plan_id(plan.key)
                state.plans[pid] = MockPlan(id=pid, key=plan.key, name=plan.name, currency=plan.currency,
                                            billing_cycles=[c.model_copy() for c in plan.billing_cycles])

    def _sub(self, state: MockPayPalState, sub_id: str) -> MockSub:
        sub = state.subscriptions.get(sub_id)
        if sub is None:
            raise PayPalError("subscription not found", status=404, name="RESOURCE_NOT_FOUND",
                              issues=["INVALID_RESOURCE_ID"], transport="mock")
        return sub

    @staticmethod
    def _view(sub: MockSub) -> SubscriptionView:
        return SubscriptionView(id=sub.id, status=sub.status, plan_id=sub.plan_id,
                                start_time=sub.start_time.isoformat() if sub.start_time else None)

    # ---- backend API --------------------------------------------------------
    async def get_subscription(self, sub_id: str, *, merchant: Merchant | None = None) -> SubscriptionView:
        self._maybe_fail("get_subscription")
        async with self.store.aedit("mock_paypal") as state:
            return self._view(self._sub(state, sub_id))

    async def create_subscription(self, plan_id: str, *, request_id: str, return_url: str | None = None,
                                  cancel_url: str | None = None,
                                  merchant: Merchant | None = None) -> SubscriptionView:
        self._maybe_fail("create_subscription")
        async with self.store.aedit("mock_paypal") as state:
            self._ensure_plans(state)
            if plan_id not in state.plans:
                raise PayPalError("plan not found", status=404, name="RESOURCE_NOT_FOUND", transport="mock")
            if request_id in state.seen_request_ids:  # idempotent replay, like PayPal-Request-Id
                return self._view(state.subscriptions[state.seen_request_ids[request_id]])
            sub = MockSub(id="I-MOCK" + secrets.token_hex(5).upper(), plan_id=plan_id, create_time=utcnow())
            state.subscriptions[sub.id] = sub
            state.seen_request_ids[request_id] = sub.id
            return self._view(sub)

    async def approve(self, sub_id: str) -> SubscriptionView:
        """What the buyer's 'Mock PayPal approval' click does."""
        async with self.store.aedit("mock_paypal") as state:
            sub = self._sub(state, sub_id)
            if sub.status == "APPROVAL_PENDING":
                sub.status, sub.start_time, sub.update_time = "ACTIVE", utcnow(), utcnow()
            return self._view(sub)

    async def set_status(self, sub_id: str, status: str, note: str = "") -> SubscriptionView:
        """Merchant-side change for display (SUSPENDED / EXPIRED), used by corner-case tests."""
        async with self.store.aedit("mock_paypal") as state:
            sub = self._sub(state, sub_id)
            sub.status, sub.status_change_note, sub.update_time = status, note, utcnow()  # type: ignore[assignment]
            return self._view(sub)

    async def cancel_subscription(self, sub_id: str, reason: str, *, request_id: str,
                                  merchant: Merchant | None = None) -> str | None:
        self._maybe_fail("cancel")
        async with self.store.aedit("mock_paypal") as state:
            sub = self._sub(state, sub_id)
            if sub.status not in ("ACTIVE", "SUSPENDED"):
                raise PayPalError("Invalid subscription status for cancel action", status=422,
                                  name="UNPROCESSABLE_ENTITY", issues=["SUBSCRIPTION_STATUS_INVALID"],
                                  debug_id=f"mock-{secrets.token_hex(4)}", transport="mock")
            sub.status, sub.status_change_note, sub.update_time = "CANCELLED", reason, utcnow()
        return f"mock-{secrets.token_hex(4)}"

    async def get_subscription_meta(self, sub_id: str, *,
                                    merchant: Merchant | None = None) -> tuple[SubscriptionView, str | None]:
        return await self.get_subscription(sub_id, merchant=merchant), f"mock-{secrets.token_hex(4)}"

    async def get_plan_meta(self, plan_id: str, *, merchant: Merchant | None = None) -> tuple[PlanView, str | None]:
        return await self.get_plan(plan_id, merchant=merchant), f"mock-{secrets.token_hex(4)}"

    async def get_plan(self, plan_id: str, *, merchant: Merchant | None = None) -> PlanView:
        self._maybe_fail("get_plan")
        async with self.store.aedit("mock_paypal") as state:
            self._ensure_plans(state)
            plan = state.plans.get(plan_id)
            if plan is None:
                raise PayPalError("plan not found", status=404, name="RESOURCE_NOT_FOUND", transport="mock")
            return PlanView(id=plan.id, name=plan.name, status=plan.status, currency=plan.currency,
                            billing_cycles=[c.model_copy() for c in plan.billing_cycles])

    async def update_pricing(self, plan_id: str, sequence: int, price: Decimal, currency: str, *,
                             request_id: str, merchant: Merchant | None = None) -> None:
        self._maybe_fail("update_pricing")
        async with self.store.aedit("mock_paypal") as state:
            self._ensure_plans(state)
            plan = state.plans.get(plan_id)
            if plan is None or not 1 <= sequence <= len(plan.billing_cycles):
                raise PayPalError("plan or billing cycle not found", status=404, name="RESOURCE_NOT_FOUND",
                                  transport="mock")
            plan.billing_cycles[sequence - 1].price = price

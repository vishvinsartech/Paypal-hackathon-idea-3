"""Types shared by every PayPal backend (mock, SDK, MCP) and the gateway facade."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel

from app.models import BillingCycleDef, Merchant

TERMINAL = {"CANCELLED", "EXPIRED"}
DAYS_PER_UNIT = {"DAY": 1, "WEEK": 7, "MONTH": 30, "YEAR": 365}


class PayPalError(Exception):
    """One error shape for every backend. `retryable` covers 5xx/408/429 and no-response."""

    def __init__(
        self, message: str, *, status: int | None = None, name: str | None = None,
        debug_id: str | None = None, issues: Sequence[str] = (), retryable: bool = False,
        transport: str = "sdk",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.name = name
        self.debug_id = debug_id
        self.issues = list(issues)
        self.retryable = retryable
        self.transport = transport

    @property
    def status_invalid(self) -> bool:
        """PayPal's 422 for acting on a subscription in the wrong state (e.g. already cancelled)."""
        return self.status == 422 or "SUBSCRIPTION_STATUS_INVALID" in self.issues

    def summary(self) -> str:
        parts = [str(self.status or "no-response"), self.name or "", ",".join(self.issues)]
        return ":".join(p for p in parts if p)


class SubscriptionView(BaseModel):
    id: str
    status: str | None = None
    plan_id: str | None = None
    start_time: str | None = None
    next_billing_time: str | None = None
    approve_url: str | None = None


class PlanView(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    currency: str = "USD"
    billing_cycles: list[BillingCycleDef]


class PayPalBackend(Protocol):
    transport: str

    async def get_subscription(self, sub_id: str, *, merchant: Merchant | None = None) -> SubscriptionView: ...

    async def cancel_subscription(self, sub_id: str, reason: str, *, request_id: str,
                                  merchant: Merchant | None = None) -> str | None:
        """Returns PayPal's debug id for the call when the transport exposes it (SDK/REST, mock), else None."""
        ...


class FullBackend(PayPalBackend, Protocol):
    """Mock and SDK implement everything; MCP only reads + cancels."""

    async def get_plan(self, plan_id: str, *, merchant: Merchant | None = None) -> PlanView: ...

    async def get_subscription_meta(self, sub_id: str, *,
                                    merchant: Merchant | None = None) -> tuple[SubscriptionView, str | None]:
        """Live read + PayPal's `paypal-debug-id` response header (the live verification card, D-113)."""
        ...

    async def get_plan_meta(self, plan_id: str, *, merchant: Merchant | None = None) -> tuple[PlanView, str | None]: ...

    async def update_pricing(self, plan_id: str, sequence: int, price: Decimal, currency: str, *,
                             request_id: str, merchant: Merchant | None = None) -> None: ...

    async def create_subscription(self, plan_id: str, *, request_id: str, return_url: str | None = None,
                                  cancel_url: str | None = None,
                                  merchant: Merchant | None = None) -> SubscriptionView: ...


def debug_header(headers: Any) -> str | None:
    """`paypal-debug-id` from a response's headers, whatever their case."""
    for key, value in dict(headers or {}).items():
        if str(key).lower() == "paypal-debug-id":
            return str(value)
    return None


def subscription_view(data: dict[str, Any], fallback_id: str = "") -> SubscriptionView:
    """PayPal subscription JSON (REST, SDK `.text` or MCP) -> SubscriptionView."""
    billing = data.get("billing_info") or {}
    approve = next((link.get("href") for link in data.get("links") or [] if link.get("rel") == "approve"), None)
    return SubscriptionView(id=data.get("id") or fallback_id, status=data.get("status"), plan_id=data.get("plan_id"),
                            start_time=data.get("start_time"), next_billing_time=billing.get("next_billing_time"),
                            approve_url=approve)


def plan_view(data: dict[str, Any]) -> PlanView:
    """PayPal billing plan JSON -> PlanView (prices as Decimal, cycles in sequence order)."""
    cycles, currency = [], "USD"
    for c in sorted(data.get("billing_cycles") or [], key=lambda c: c.get("sequence", 0)):
        price = ((c.get("pricing_scheme") or {}).get("fixed_price")) or {}
        currency = price.get("currency_code", currency)
        freq = c.get("frequency") or {}
        cycles.append(BillingCycleDef(
            tenure_type=c["tenure_type"], price=Decimal(price.get("value", "0")),
            interval_unit=freq.get("interval_unit", "MONTH"), interval_count=freq.get("interval_count", 1),
            total_cycles=c.get("total_cycles", 1),
        ))
    return PlanView(id=data["id"], name=data.get("name"), status=data.get("status"), currency=currency,
                    billing_cycles=cycles)


def cycle_days(cycle: BillingCycleDef) -> int:
    return DAYS_PER_UNIT[cycle.interval_unit] * cycle.interval_count


def _leading_free_days(cycles: Sequence[BillingCycleDef]) -> int:
    days = 0
    for c in cycles:
        if c.price > 0:
            break
        days += cycle_days(c) * max(c.total_cycles, 1)
    return days


def first_charge_day(cycles: Sequence[BillingCycleDef], signup_day: int) -> int:
    """Day of the first paid charge. A 10-day free trial from Day 0 charges on Day 11 (spec section 2).
    Only the leading free cycles count: a paid TRIAL cycle (intro price, D-031) is already a charge."""
    free = _leading_free_days(cycles)
    if free:
        return signup_day + free + 1
    paid = next((c for c in cycles if c.price > 0), None)
    return signup_day + (cycle_days(paid) if paid else 30)


def first_paid_price(cycles: Sequence[BillingCycleDef]) -> Decimal:
    """Price of the first charge: the first cycle with a price, TRIAL (intro) or REGULAR."""
    paid = next((c for c in cycles if c.price > 0), None)
    return paid.price if paid else Decimal("0")

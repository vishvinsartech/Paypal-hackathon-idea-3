"""Pydantic models for every runtime JSON file. Later milestones extend these."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

SubStatus = Literal["APPROVAL_PENDING", "APPROVED", "ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED"]
TimerStatus = Literal["PENDING", "KEPT", "FIRED", "FAILED", "CANCELLED"]


# ---- state.json -------------------------------------------------------------
class State(BaseModel):
    sim_day: int = 0
    app_mode: str = "mock"
    last_tick_day: int | None = None
    last_tick_at: datetime | None = None


# ---- users.json -------------------------------------------------------------
class UserSettings(BaseModel):
    auto_cancel_price_rises: bool = False
    channels: list[Literal["in_app", "email", "sms"]] = Field(default_factory=lambda: ["in_app", "email"])


class User(BaseModel):
    id: str
    name: str
    persona: str = ""
    email: str = ""
    phone: str = ""
    settings: UserSettings = Field(default_factory=UserSettings)


class UserList(BaseModel):
    items: list[User] = Field(default_factory=list)


# ---- merchants.json ---------------------------------------------------------
class BillingCycleDef(BaseModel):
    tenure_type: Literal["TRIAL", "REGULAR"]
    price: Decimal
    interval_unit: Literal["DAY", "WEEK", "MONTH", "YEAR"]
    interval_count: int = 1
    total_cycles: int = 0  # 0 = unlimited (PayPal convention)


class PlanDef(BaseModel):
    key: str
    name: str
    currency: str = "USD"
    billing_cycles: list[BillingCycleDef]
    addon: bool = False


class Merchant(BaseModel):
    id: str
    name: str
    tagline: str = ""
    fair_trial_member: bool = True
    support_email: str = ""
    paypal_payer_id: str = ""
    plans: list[PlanDef] = Field(default_factory=list)


class MerchantList(BaseModel):
    items: list[Merchant] = Field(default_factory=list)


# ---- subscriptions.json -----------------------------------------------------
class ConsentSnapshot(BaseModel):
    taken_at: datetime
    sim_day: int
    price: Decimal
    currency: str = "USD"
    terms_summary: str = ""
    billing_cycles: list[BillingCycleDef] = Field(default_factory=list)


class Subscription(BaseModel):
    id: str
    paypal_id: str
    plan_key: str
    plan_id: str
    merchant_id: str
    owner_id: str
    status: SubStatus = "APPROVAL_PENDING"
    essential: bool = False
    signup_day: int = 0
    next_billing_day: int | None = None
    addon_of: str | None = None
    consent_snapshot: ConsentSnapshot | None = None
    registered_at: datetime | None = None
    cancel_requested_at: datetime | None = None  # duplicate-cancel claim (released on failure)
    cancelled_at: datetime | None = None
    last_synced_at: datetime | None = None


class SubscriptionList(BaseModel):
    items: list[Subscription] = Field(default_factory=list)


# ---- reviews.json -----------------------------------------------------------
class Review(BaseModel):
    id: str
    merchant_id: str
    subscription_id: str | None = None
    created_at: datetime
    risk_score: int = 0
    data: dict[str, Any] = Field(default_factory=dict)  # full ReviewResult, typed in milestone 4


class ReviewList(BaseModel):
    items: list[Review] = Field(default_factory=list)


# ---- timers.json ------------------------------------------------------------
class Timer(BaseModel):
    id: str
    subscription_id: str
    kind: Literal["trial", "price_rise"] = "trial"
    fire_day: int
    status: TimerStatus = "PENDING"
    shown_to_user: bool = False
    warned_at: datetime | None = None
    warned_day: int | None = None
    warning_delivered: bool = False


class TimerList(BaseModel):
    items: list[Timer] = Field(default_factory=list)


# ---- alerts.json ------------------------------------------------------------
class Alert(BaseModel):
    id: str
    user_id: str
    level: Literal["info", "warning", "urgent", "action_needed"] = "info"
    title: str
    body: str = ""
    actions: list[dict[str, str]] = Field(default_factory=list)
    subscription_id: str | None = None
    sim_day: int = 0
    created_at: datetime
    delivery: dict[str, str] = Field(default_factory=dict)  # channel -> accepted|failed|mocked
    acknowledged_at: datetime | None = None
    idempotency_key: str


class AlertList(BaseModel):
    items: list[Alert] = Field(default_factory=list)


# ---- tokens.json ------------------------------------------------------------
class ConfirmToken(BaseModel):
    token: str
    user_id: str
    subscription_ids: list[str]
    issued_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


class TokenList(BaseModel):
    items: list[ConfirmToken] = Field(default_factory=list)


# ---- usage.json -------------------------------------------------------------
class UsageEvent(BaseModel):
    user_id: str
    merchant_id: str
    subscription_id: str | None = None
    day: int
    kind: Literal["open", "export"] = "open"
    at: datetime


class UsageList(BaseModel):
    items: list[UsageEvent] = Field(default_factory=list)


# ---- notices.json -----------------------------------------------------------
class Notice(BaseModel):
    id: str
    subscription_id: str
    to: str
    subject: str
    body: str
    sha256: str
    sent_at: datetime
    delivery: str = "pending"


class NoticeList(BaseModel):
    items: list[Notice] = Field(default_factory=list)


# ---- mock_paypal.json (PayPal's side of the world, mock mode only) -----------
class MockPlan(BaseModel):
    id: str
    key: str
    name: str
    currency: str = "USD"
    status: str = "ACTIVE"
    billing_cycles: list[BillingCycleDef]


class MockSub(BaseModel):
    id: str
    plan_id: str
    status: SubStatus = "APPROVAL_PENDING"
    status_change_note: str | None = None
    create_time: datetime
    start_time: datetime | None = None
    update_time: datetime | None = None


class MockPayPalState(BaseModel):
    plans: dict[str, MockPlan] = Field(default_factory=dict)
    subscriptions: dict[str, MockSub] = Field(default_factory=dict)
    seen_request_ids: dict[str, str] = Field(default_factory=dict)  # PayPal-Request-Id -> result id


# ---- sandbox_ids.json -------------------------------------------------------
class SandboxIds(BaseModel):
    products: dict[str, str] = Field(default_factory=dict)  # merchant_id -> product id
    plans: dict[str, str] = Field(default_factory=dict)  # plan key -> plan id

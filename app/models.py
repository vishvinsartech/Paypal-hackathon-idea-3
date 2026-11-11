"""Pydantic models for every runtime JSON file. Later milestones extend these."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.review_types import ReviewData

SubStatus = Literal["APPROVAL_PENDING", "APPROVED", "ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED"]
TimerStatus = Literal["PENDING", "KEPT", "FIRED", "FAILED", "CANCELLED"]


# ---- state.json -------------------------------------------------------------
class Reminder(BaseModel):
    """A reminder the chat agent scheduled (schedule_reminder); sent as an in-app alert on `day`."""

    id: str
    user_id: str
    subscription_id: str
    day: int
    note: str = ""
    sent: bool = False


class State(BaseModel):
    sim_day: int = 0
    app_mode: str = "mock"
    last_tick_day: int | None = None
    last_tick_at: datetime | None = None
    pricing_fingerprint: str | None = None  # which .env prices this runtime data was built with
    demo_seeded: bool = False  # Priya's scripted Penwright usage created (mock mode, DEMO_SEED)
    reminders: list[Reminder] = Field(default_factory=list)
    webhook_event_ids: list[str] = Field(default_factory=list)  # last 500 PayPal webhook ids (dedupe)


# ---- users.json -------------------------------------------------------------
class UserSettings(BaseModel):
    auto_cancel_price_rises: bool = False
    channels: list[Literal["in_app", "email", "sms"]] = Field(default_factory=lambda: ["in_app", "email"])


class User(BaseModel):
    id: str
    name: str  # display name ("Priya")
    full_name: str = ""  # as written in letters (the cancellation email); falls back to name
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
    auto_send_notice: bool = False  # D7: "If I don't answer, send the cancellation email for me" (opt-in)


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
    kept_day: int | None = None  # sim day the user tapped Keep (no more prompts after that)
    consent_snapshot: ConsentSnapshot | None = None
    registered_at: datetime | None = None
    cancel_requested_at: datetime | None = None  # duplicate-cancel claim (released on failure)
    cancelled_at: datetime | None = None
    cancelled_day: int | None = None
    cancelled_by: Literal["user", "timer", "external"] | None = None
    protected_year_usd: Decimal | None = None  # year-one cost avoided, from the PayPal plan at cancel time
    last_synced_at: datetime | None = None


class SubscriptionList(BaseModel):
    items: list[Subscription] = Field(default_factory=list)


# ---- reviews.json -----------------------------------------------------------
class Review(BaseModel):
    id: str
    merchant_id: str
    subscription_id: str | None = None
    created_at: datetime
    sim_day: int = 0
    risk_score: int = 0
    data: ReviewData
    auto_send_notice: bool = False  # D7 checkbox in the companion, copied to the consent snapshot at sign-up


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
    warning_basis: str | None = None  # zapier_accepted | zapier_mocked | zapier_down_in_app_only
    created_day: int = 0
    deadline_day: int | None = None
    reminder_day: int | None = None
    billing_day: int | None = None  # the charge this timer protects against
    layer2: bool = False
    note: str = ""


class TimerList(BaseModel):
    items: list[Timer] = Field(default_factory=list)


# ---- alerts.json ------------------------------------------------------------
class Alert(BaseModel):
    id: str
    user_id: str
    kind: str = ""  # timer_set | reminder | cancelled | blocked_charge | urgent | ...
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
    source: Literal["live", "seed"] = "live"  # seed = scripted demo usage (D-053)


class UsageList(BaseModel):
    items: list[UsageEvent] = Field(default_factory=list)


# ---- notices.json -----------------------------------------------------------
class Notice(BaseModel):
    """The cancellation email to the merchant (D-104): drafted after the PayPal cancel, edited and sent by the user
    (demo only: "sent" means saved to the outbox, or handed to a Gmail compose link). Never sent without a click."""

    id: str
    subscription_id: str
    merchant_id: str = ""
    sim_day: int = 0
    to: str
    subject: str
    body: str
    sha256: str  # of `body` (the final text once sent)
    status: Literal["draft", "sent"] = "draft"
    drafted_by: str = "standard template"  # "anthropic · <model>", "mock · fixtures" or "standard template"
    draft_source: Literal["llm", "template"] = "template"
    draft_problems: list[str] = Field(default_factory=list)  # why the LLM draft was rejected (template used)
    draft_to: str = ""
    draft_subject: str = ""
    draft_body: str = ""
    created_at: datetime | None = None
    by_timer: bool = False
    edited: bool | None = None
    sent_at: datetime | None = None
    sent_via: Literal["demo_outbox", "gmail_compose_link", "auto_on_timer"] | None = None
    delivery: str = "draft"  # draft | demo_outbox | gmail_compose_link | auto_on_timer (D7 opt-in)


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
    demo_subscriptions: dict[str, str] = Field(default_factory=dict)  # plan key -> subscription id (--demo-subs)

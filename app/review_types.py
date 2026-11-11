"""Fine-print review types shared by the LLM providers, the auditor, the store and the routes (spec 7.2)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ClauseType = Literal[
    "AUTO_RENEW", "INTRO_PRICE_STEP_UP", "PRECHECKED_ADDON", "NOTICE_PERIOD", "EARLY_TRIAL_TERMINATION",
    "HARD_CANCEL", "HIDDEN_TEXT_STYLE", "TERMS_MISMATCH", "PROMPT_INJECTION_ATTEMPT", "CLEAR_TERMS",
]
CLAUSE_TYPES: tuple[str, ...] = ClauseType.__args__  # type: ignore[attr-defined]
ClauseSource = Literal["llm", "rules", "paypal_check", "code"]
TYPE_LABELS: dict[str, str] = {  # plain labels for user surfaces (never the raw enum)
    "AUTO_RENEW": "Turns into a paid plan", "INTRO_PRICE_STEP_UP": "Price goes up later",
    "PRECHECKED_ADDON": "Add-on ticked for you", "NOTICE_PERIOD": "Notice needed before billing",
    "EARLY_TRIAL_TERMINATION": "Trial can end early", "HARD_CANCEL": "Hard to cancel",
    "HIDDEN_TEXT_STYLE": "Hard-to-read terms", "TERMS_MISMATCH": "Page and PayPal plan disagree",
    "PROMPT_INJECTION_ATTEMPT": "Hidden instructions to AI", "CLEAR_TERMS": "Clear terms",
}


def _lenient_decimal(value: Any) -> Decimal | None:
    """LLM money hints are advisory (code recomputes money from PayPal); bad values become None."""
    if value is None or value == "":
        return None
    if isinstance(value, float):
        value = repr(value)
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return None


class Clause(BaseModel):
    type: ClauseType
    quote: str
    plain_english: str
    money_impact_usd_year: Decimal | None = None
    deadline_day: int | None = None
    severity: int = Field(3, ge=1, le=5)
    evidence_testid: str | None = None
    source: ClauseSource = "llm"
    similar_pattern: str | None = None  # nearest dark-pattern library example (TF-IDF), informational

    @field_validator("money_impact_usd_year", mode="before")
    @classmethod
    def _money(cls, v: Any) -> Decimal | None:
        return _lenient_decimal(v)


class ReviewResult(BaseModel):
    """What a provider returns from `extract_findings` (strict JSON)."""

    clauses: list[Clause] = Field(default_factory=list)
    summary: str = ""
    first_charge_day: int | None = None
    first_charge_amount: Decimal | None = None
    notice_days: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict, exclude=True)  # tokens, filled by the provider

    @field_validator("first_charge_amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> Decimal | None:
        return _lenient_decimal(v)


# JSON schema sent to the providers (strict-mode friendly: every key required, no extra keys).
_NULLABLE_INT = {"type": ["integer", "null"]}
_NULLABLE_STR = {"type": ["string", "null"]}
REVIEW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["clauses", "summary", "first_charge_day", "first_charge_amount", "notice_days"],
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "quote", "plain_english", "money_impact_usd_year", "deadline_day",
                             "severity", "evidence_testid"],
                "properties": {
                    "type": {"type": "string", "enum": list(CLAUSE_TYPES)},
                    "quote": {"type": "string", "description": "Exact sentence copied verbatim from the page text"},
                    "plain_english": {"type": "string"},
                    "money_impact_usd_year": {**_NULLABLE_STR, "description": "Decimal string, e.g. \"119.88\""},
                    "deadline_day": _NULLABLE_INT,
                    "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                    "evidence_testid": _NULLABLE_STR,
                },
            },
        },
        "summary": {"type": "string"},
        "first_charge_day": {**_NULLABLE_INT, "description": "Day of the first paid charge; signup is day 0"},
        "first_charge_amount": {**_NULLABLE_STR, "description": "Decimal string"},
        "notice_days": {**_NULLABLE_INT, "description": "Days of notice required before billing to cancel"},
    },
}


class PayPalCheckRow(BaseModel):
    item: str
    page_says: str
    paypal_says: str
    match: bool
    label: str = ""  # U16: the row in plain words ("Price $24.99 shown only in fine print"); old reviews: ""


class Deadlines(BaseModel):
    signup_day: int
    first_charge_day: int
    notice_days: int
    real_cancel_deadline_day: int  # "act by": the terms' last day minus SubGuard's 1-day safety margin
    terms_last_day: int | None = None  # D6: the last day the terms allow (first charge - notice)
    timer_fire_day: int
    reminder_day: int
    layer2: bool = False
    auto_timer_allowed: bool
    note: str = ""

    @model_validator(mode="after")
    def _fill_terms_last_day(self) -> Deadlines:  # reviews stored before D6 don't have it
        if self.terms_last_day is None:
            self.terms_last_day = self.first_charge_day - self.notice_days
        return self


class RiskBreakdown(BaseModel):
    type_points: dict[str, int] = Field(default_factory=dict)
    style_points: dict[str, int] = Field(default_factory=dict)
    money_factor: Decimal = Decimal("0")
    library_bonus: int = 0
    total: int = 0


class BasicCheck(BaseModel):
    """A2: what the basic (regex, no-AI) check finds on the same page, stored with every review. The code checks
    (PayPal cross-check, hard-to-read styling, injection) run on both paths, so the difference is the AI."""

    types: list[str] = Field(default_factory=list)
    clauses: list[Clause] = Field(default_factory=list)
    notice_days: int = 0
    real_cancel_deadline_day: int = 0
    terms_last_day: int = 0
    risk_score: int = 0


RISKY_EXCLUDED = frozenset({"CLEAR_TERMS", "AUTO_RENEW", "PROMPT_INJECTION_ATTEMPT"})


class ReviewData(BaseModel):
    """A finished review: findings + PayPal cross-check + deadlines + risk (stored in reviews.json)."""

    merchant_id: str
    page_url: str
    plan_id: str
    plan_key: str | None = None
    mode: Literal["ai", "basic"] = "ai"
    mode_label: str = "AI review"
    provider: str
    model: str
    summary: str = ""
    clauses: list[Clause] = Field(default_factory=list)
    paypal_check: list[PayPalCheckRow] = Field(default_factory=list)
    deadlines: Deadlines
    risk: RiskBreakdown
    risk_score: int
    currency: str = "USD"
    year_one_cost: Decimal = Decimal("0")
    style_signals: list[str] = Field(default_factory=list)
    library_matches: list[str] = Field(default_factory=list)
    dropped_quotes: list[str] = Field(default_factory=list)
    injection_flagged: bool = False
    notice_source: Literal["quote_digits", "quote_words", "ai", "none"] = "none"  # A3: where notice_days came from
    basic: BasicCheck | None = None  # A2 (reviews stored before v3 Phase 2 don't have it)

    def types(self) -> list[str]:
        return [c.type for c in self.clauses]

    def ai_vs_basic(self) -> dict[str, Any] | None:
        """A2: which finding types each path found. `ai_only_risky` excludes types every subscription has."""
        if self.basic is None or self.mode != "ai":
            return None
        ai, basic = set(self.types()), set(self.basic.types)
        order = [*dict.fromkeys([*self.types(), *self.basic.types])]
        return {"rows": [{"type": t, "ai": t in ai, "basic": t in basic} for t in order],
                "ai_only": [t for t in order if t in ai - basic],
                "ai_only_risky": [t for t in order if t in ai - basic and t not in RISKY_EXCLUDED],
                "basic_only": [t for t in order if t in basic - ai],
                "ai_risk": self.risk_score, "basic_risk": self.basic.risk_score,
                "ai_notice_days": self.deadlines.notice_days, "basic_notice_days": self.basic.notice_days,
                "ai_act_by_day": self.deadlines.real_cancel_deadline_day,
                "basic_act_by_day": self.basic.real_cancel_deadline_day}

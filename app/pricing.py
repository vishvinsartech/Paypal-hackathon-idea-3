"""Demo prices and terms, adjustable from .env (defaults = the spec's numbers).

`PricingFields` is mixed into `Settings`, so each field is an env var (e.g. PENWRIGHT_INTRO_PRICE=24.99).
Everything that shows or bills a price (merchant plans, mock PayPal, sandbox seed, shop pages) reads it
from here, so the page text and the PayPal plan always agree. Money is Decimal with at most 2 decimals.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from app.models import BillingCycleDef, PlanDef

Price = Annotated[Decimal, Field(gt=0, max_digits=9, decimal_places=2)]
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


class PricingFields(BaseModel):
    demo_currency: str = Field("USD", pattern=r"^[A-Z]{3}$")

    penwright_trial_days: int = Field(10, ge=1, le=90)
    penwright_intro_price: Price = Decimal("24.99")
    penwright_intro_months: int = Field(3, ge=1, le=24)
    penwright_step_up_price: Price = Decimal("49.99")
    penwright_notice_days: int = Field(3, ge=0, le=60)
    penwright_export_limit: int = Field(3, ge=1, le=100)


class Pricing(PricingFields):
    """The resolved values, plus the plans and display helpers derived from them."""

    @property
    def penwright_first_charge_day(self) -> int:
        return self.penwright_trial_days + 1

    def money(self, amount: Decimal | int | str, currency: str | None = None) -> str:
        """Short display: $20 for whole amounts, $24.99 otherwise. `currency` = the plan's (default: demo)."""
        amount = Decimal(str(amount))
        cur = currency or self.demo_currency
        text = f"{amount:,.0f}" if amount == amount.to_integral_value() else f"{amount:,.2f}"
        symbol = SYMBOLS.get(cur)
        return f"{symbol}{text}" if symbol else f"{text} {cur}"

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]

    def plans_for(self, merchant_id: str) -> list[PlanDef]:
        if merchant_id != "penwright":
            return []
        monthly = {"interval_unit": "MONTH", "interval_count": 1}
        return [PlanDef(key="penwright-pro", name="Penwright Pro", currency=self.demo_currency, billing_cycles=[
            BillingCycleDef(tenure_type="TRIAL", price=Decimal("0.00"), interval_unit="DAY",
                            interval_count=self.penwright_trial_days, total_cycles=1),
            # PayPal allows one REGULAR cycle per plan, so the intro price is a paid TRIAL (D-031)
            BillingCycleDef(tenure_type="TRIAL", price=self.penwright_intro_price,
                            total_cycles=self.penwright_intro_months, **monthly),  # type: ignore[arg-type]
            BillingCycleDef(tenure_type="REGULAR", price=self.penwright_step_up_price,
                            total_cycles=0, **monthly),  # type: ignore[arg-type]
        ])]

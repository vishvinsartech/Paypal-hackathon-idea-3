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

    penwright_trial_days: int = Field(14, ge=1, le=90)
    penwright_intro_price: Price = Decimal("24.99")
    penwright_intro_months: int = Field(3, ge=1, le=24)
    penwright_step_up_price: Price = Decimal("49.99")
    penwright_addon_price: Price = Decimal("9.99")
    penwright_notice_days: int = Field(7, ge=0, le=60)
    penwright_export_limit: int = Field(3, ge=1, le=100)

    framewise_price: Price = Decimal("12.00")
    framewise_rise_price: Price = Decimal("19.00")

    lumen_monthly_price: Price = Decimal("20.00")
    lumen_yearly_price: Price = Decimal("200.00")


class Pricing(PricingFields):
    """The resolved values, plus the plans and display helpers derived from them."""

    @property
    def penwright_first_charge_day(self) -> int:
        return self.penwright_trial_days + 1

    def money(self, amount: Decimal | int | str) -> str:
        """Short display: $20 for whole amounts, $24.99 otherwise."""
        amount = Decimal(str(amount))
        text = f"{amount:,.0f}" if amount == amount.to_integral_value() else f"{amount:,.2f}"
        symbol = SYMBOLS.get(self.demo_currency)
        return f"{symbol}{text}" if symbol else f"{text} {self.demo_currency}"

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]

    def _plan(self, key: str, name: str, cycles: list[BillingCycleDef], addon: bool = False) -> PlanDef:
        return PlanDef(key=key, name=name, currency=self.demo_currency, billing_cycles=cycles, addon=addon)

    def plans_for(self, merchant_id: str) -> list[PlanDef]:
        monthly = {"interval_unit": "MONTH", "interval_count": 1}
        if merchant_id == "penwright":
            return [
                self._plan("penwright-pro", "Penwright Pro", [
                    BillingCycleDef(tenure_type="TRIAL", price=Decimal("0.00"), interval_unit="DAY",
                                    interval_count=self.penwright_trial_days, total_cycles=1),
                    BillingCycleDef(tenure_type="REGULAR", price=self.penwright_intro_price,
                                    total_cycles=self.penwright_intro_months, **monthly),  # type: ignore[arg-type]
                    BillingCycleDef(tenure_type="REGULAR", price=self.penwright_step_up_price,
                                    total_cycles=0, **monthly),  # type: ignore[arg-type]
                ]),
                self._plan("penwright-ai-pack", "AI Writing Pack add-on", [
                    BillingCycleDef(tenure_type="REGULAR", price=self.penwright_addon_price, total_cycles=0,
                                    **monthly),  # type: ignore[arg-type]
                ], addon=True),
            ]
        if merchant_id == "framewise":
            return [self._plan("framewise-basic", "Framewise Basic", [
                BillingCycleDef(tenure_type="REGULAR", price=self.framewise_price, total_cycles=0,
                                **monthly)])]  # type: ignore[arg-type]
        if merchant_id == "lumen":
            return [
                self._plan("lumen-monthly", "Lumen Notes Monthly", [
                    BillingCycleDef(tenure_type="REGULAR", price=self.lumen_monthly_price, total_cycles=0,
                                    **monthly)]),  # type: ignore[arg-type]
                self._plan("lumen-yearly", "Lumen Notes Yearly", [
                    BillingCycleDef(tenure_type="REGULAR", price=self.lumen_yearly_price, interval_unit="YEAR",
                                    interval_count=1, total_cycles=0)]),
            ]
        return []

"""The Live demo page's product landing section (D-173): hero, Priya's card, how it works, built with.

Every number comes from `settings.pricing` (never hardcoded): the Penwright offer, its traps, and the year-one cost.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.core.savings import year_one_cost


def ai_model_label(settings: Settings) -> str:
    """The active AI model from config. Mock mode uses recorded answers, so say so (no fake claims)."""
    if settings.is_sandbox:
        return f"AI model: {settings.llm_model}"
    configured = settings.anthropic_model if settings.llm_provider == "anthropic" else settings.openai_model
    return f"AI model: {configured} (recorded answers here)" if configured else "AI model: recorded answers here"


def landing_view(settings: Settings) -> dict[str, Any]:
    p = settings.pricing
    (plan,) = p.plans_for("penwright")
    terms_last_day = p.penwright_first_charge_day - p.penwright_notice_days
    return {
        "trial_days": p.penwright_trial_days,
        "intro": p.money(p.penwright_intro_price),
        "intro_months": p.penwright_intro_months,
        "step_up": p.money(p.penwright_step_up_price),
        "notice_days": p.penwright_notice_days,
        "terms_last_day": terms_last_day,
        "act_by_day": terms_last_day - 1,  # D-132: one day of margin
        "first_charge_day": p.penwright_first_charge_day,
        "year_one": p.money(year_one_cost(plan.billing_cycles)),
        "zero": p.money(0),
        "ai_model": ai_model_label(settings),
    }

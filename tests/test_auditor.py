"""Fine-print review pipeline (spec 7.2) with the mock provider and scripted stubs. Milestone 4 check."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from app.config import Settings
from app.core.patterns import quote_ok
from app.core.risk import compute_deadlines
from app.core.savings import year_one_cost
from app.llm.base import LLMError
from app.llm.mock_provider import MockProvider
from app.pricing import Pricing
from app.store import JsonStore
from tests.review_helpers import FIXTURES, ScriptedProvider, capture_page, mock_text, plan_for, run_review


def test_penwright_review_matches_spec(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    data = run_review(store, MockProvider(FIXTURES, Pricing()), cap, "penwright-pro")
    types = data.types()
    assert len(data.clauses) >= 7
    for t in ("NOTICE_PERIOD", "TERMS_MISMATCH", "PROMPT_INJECTION_ATTEMPT", "PRECHECKED_ADDON",
              "INTRO_PRICE_STEP_UP", "HARD_CANCEL", "EARLY_TRIAL_TERMINATION", "HIDDEN_TEXT_STYLE"):
        assert t in types
    assert abs(data.risk_score - 87) <= 5
    d = data.deadlines
    assert (d.first_charge_day, d.notice_days, d.real_cancel_deadline_day, d.timer_fire_day, d.reminder_day) == (
        15, 7, 7, 6, 5)
    assert d.auto_timer_allowed and data.mode == "ai" and data.injection_flagged
    assert all(quote_ok(c.quote, cap) for c in data.clauses), "every quote must be verbatim"
    money = {c.type: c.money_impact_usd_year for c in data.clauses}
    assert money["INTRO_PRICE_STEP_UP"] == Decimal("524.88") and money["PRECHECKED_ADDON"] == Decimal("119.88")
    assert set(data.style_signals) == {"small_font", "low_contrast", "prechecked_box", "hidden_text"}
    assert any(not r.match for r in data.paypal_check)  # the headline hides PayPal's prices


def test_lumen_is_low_risk_and_clear(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/lumen")
    data = run_review(store, MockProvider(FIXTURES, Pricing()), cap, "lumen-monthly")
    assert abs(data.risk_score - 15) <= 5
    assert "CLEAR_TERMS" in data.types() and "TERMS_MISMATCH" not in data.types()
    assert not data.style_signals and not data.injection_flagged
    assert all(r.match for r in data.paypal_check)


def test_injection_never_changes_the_score(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    with_injection = run_review(store, MockProvider(FIXTURES, Pricing()), cap, "penwright-pro")
    clean = cap.model_copy(deep=True)
    clean.blocks = [b for b in clean.blocks if b.testid != "tos-hidden"]
    fixture = json.loads(mock_text("penwright"))
    fixture["clauses"] = [c for c in fixture["clauses"] if c["type"] != "PROMPT_INJECTION_ATTEMPT"]
    without = run_review(store, ScriptedProvider(json.dumps(fixture)), clean, "penwright-pro")
    assert not without.injection_flagged
    assert with_injection.risk_score == without.risk_score


def test_hallucinated_quote_dropped_and_retried_once(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    good = json.loads(mock_text("penwright"))
    bad = json.loads(mock_text("penwright"))
    bad["clauses"][0]["quote"] = "Cancel anytime with one click, no questions asked."
    stub = ScriptedProvider(json.dumps(bad), json.dumps(good))
    data = run_review(store, stub, cap, "penwright-pro")
    assert stub.feedbacks[0] is None and "not found verbatim" in (stub.feedbacks[1] or "")
    assert data.dropped_quotes == ["Cancel anytime with one click, no questions asked."]
    assert all(quote_ok(c.quote, cap) for c in data.clauses) and data.mode == "ai"


def test_hallucination_twice_keeps_only_verified(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    bad = json.loads(mock_text("penwright"))
    bad["clauses"][0]["quote"] = "This sentence is not on the page."
    data = run_review(store, ScriptedProvider(json.dumps(bad)), cap, "penwright-pro")
    assert "This sentence is not on the page." not in [c.quote for c in data.clauses]
    assert all(quote_ok(c.quote, cap) for c in data.clauses)


def test_llm_down_uses_labelled_rule_fallback(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    stub = ScriptedProvider(LLMError("unreachable"))
    data = run_review(store, stub, cap, "penwright-pro")
    assert len(stub.feedbacks) == 2  # 1 retry, then fallback
    assert data.mode == "basic" and data.mode_label == "basic check (AI unavailable)"
    assert {"NOTICE_PERIOD", "PROMPT_INJECTION_ATTEMPT", "TERMS_MISMATCH"} <= set(data.types())
    assert all(quote_ok(c.quote, cap) for c in data.clauses)
    assert data.deadlines.real_cancel_deadline_day == 7
    events = [e for e in store.audit.entries() if e.event == "llm_call"]
    assert len(events) == 2 and all(e.result and e.result.startswith("error") for e in events)


def test_invalid_json_then_valid_is_retried(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/lumen")
    data = run_review(store, ScriptedProvider("{not json", mock_text("lumen")), cap, "lumen-monthly")
    assert data.mode == "ai"


def test_slow_llm_times_out_to_fallback(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/lumen")
    data = run_review(store, ScriptedProvider(lambda: asyncio.sleep(1)), cap, "lumen-monthly", timeout=0.05)
    assert data.mode == "basic"


def test_layer2_merchant_fires_timer_two_days_early(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    data = run_review(store, MockProvider(FIXTURES, Pricing()), cap, "penwright-pro", fair_trial=False)
    assert data.deadlines.layer2 and data.deadlines.timer_fire_day == 5 and data.deadlines.reminder_day == 4


def test_short_trial_gets_no_auto_timer() -> None:
    d = compute_deadlines(0, 3, 2, layer2=False)  # first charge day 3, 2 days notice -> deadline day 0
    assert not d.auto_timer_allowed and "decide" in d.note
    assert compute_deadlines(0, 15, 7, layer2=False).auto_timer_allowed


def test_price_on_paypal_differs_from_page_is_mismatch(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/framewise")
    plan = plan_for("framewise-basic", price_override=Decimal("19.00"))
    data = run_review(store, MockProvider(FIXTURES, Pricing()), cap, "framewise-basic", plan=plan)
    mismatch = next(c for c in data.clauses if c.type == "TERMS_MISMATCH")
    assert "$19" in mismatch.plain_english and data.year_one_cost == Decimal("228.00")


def test_year_one_costs_from_paypal_cycles() -> None:
    assert year_one_cost(plan_for("penwright-pro").billing_cycles) == Decimal("524.88")
    assert year_one_cost(plan_for("penwright-ai-pack").billing_cycles) == Decimal("119.88")
    assert year_one_cost(plan_for("lumen-yearly").billing_cycles) == Decimal("200.00")
    assert year_one_cost(plan_for("lumen-monthly").billing_cycles) == Decimal("240.00")

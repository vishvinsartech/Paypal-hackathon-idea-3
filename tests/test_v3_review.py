"""v3 Phase 1 review fixes: B10 (no CLEAR_TERMS next to dark patterns), D6 (act by vs terms' last day),
B2 (the companion speaks relative to sign-up, never in sim days)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.patterns import drop_clear_terms_if_risky
from app.core.sub_dates import companion_display
from app.llm.base import LLMError
from app.llm.mock_provider import MockProvider
from app.pricing import Pricing
from app.review_types import Clause
from app.store import JsonStore
from tests.review_helpers import FIXTURES, ScriptedProvider, capture_page, mock_text, run_review
from tests.story_helpers import ACT_BY, advance_to


def test_basic_check_never_calls_the_trap_page_clear(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    data = run_review(store, ScriptedProvider(LLMError("down")), cap, "penwright-pro")
    assert data.mode == "basic"
    assert "NOTICE_PERIOD" in data.types() and "CLEAR_TERMS" not in data.types()


def test_ai_clear_terms_dropped_when_risky_types_present(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    fixture = json.loads(mock_text("penwright"))
    quote = fixture["clauses"][0]["quote"]  # any verified quote
    fixture["clauses"].append({**fixture["clauses"][0], "type": "CLEAR_TERMS", "quote": quote})
    data = run_review(store, ScriptedProvider(json.dumps(fixture)), cap, "penwright-pro")
    assert data.mode == "ai" and "CLEAR_TERMS" not in data.types()
    assert abs(data.risk_score - 87) <= 5


def test_clear_terms_kept_on_honest_terms() -> None:
    honest = [Clause(type="CLEAR_TERMS", quote="Cancel anytime.", plain_english="Clear."),
              Clause(type="AUTO_RENEW", quote="Renews monthly.", plain_english="Renews.")]
    assert [c.type for c in drop_clear_terms_if_risky(honest)] == ["CLEAR_TERMS", "AUTO_RENEW"]


# ---- D6: act-by Day 7 vs the terms' last day, Day 8 --------------------------------------------------------------

def test_deadline_act_by_and_terms_last_day(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    d = run_review(store, MockProvider(FIXTURES, Pricing()), cap, "penwright-pro").deadlines
    assert (d.real_cancel_deadline_day, d.terms_last_day, d.first_charge_day, d.notice_days) == (7, 8, 11, 3)
    start = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
    shown = companion_display(d, start)
    assert shown["act_by_text"] == "Act by Nov 18 (the terms allow Nov 19)"
    assert shown["points"]["first_charge"]["date"] == "Nov 22" and shown["trap"]


# ---- B2: the companion's text is relative to sign-up, whatever the sim clock says --------------------------------

def _companion_text(client: TestClient) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pre = client.post("/api/review/preflight", json={"merchant_url": "/shop/penwright",
                                                      "plan_key": "penwright-pro"}).json()
    return pre["display"], pre["paypal_check"]


def test_companion_same_text_on_day_0_and_day_11(demo_client: TestClient) -> None:
    day0 = _companion_text(demo_client)
    advance_to(demo_client, 11)
    day11 = _companion_text(demo_client)
    assert day0 == day11  # dates are from "now", offsets from sign-up: nothing depends on the sim day
    display, rows = day11
    assert display["act_by_text"] == ACT_BY and display["points"]["act_by"]["relative"] == "7 days after you start"
    first = next(r for r in rows if r["item"] == "First charge")
    assert first["page_says"] == first["paypal_says"] == "11 days after you start" and first["match"]
    assert "Day 18" not in str(display) and "Day 22" not in str(display)

"""v3 Phase 2: what the AI adds ("turn the AI off: what changes?").

A1 Quillnote, A2 AI vs basic check (recorded fixture: data/fixtures/llm/quillnote.json), A3 notice periods in words,
A4 score calibration, A5 the Layer 2 beat, A6 no mock labels on user surfaces.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app.config import ROOT_DIR, Settings
from app.core.auditor import Auditor
from app.core.durations import duration_days, number_words
from app.integrations.capture import PageCapture, StaticCapture
from app.integrations.paypal_types import PlanView
from app.llm.mock_provider import MockProvider
from app.models import BillingCycleDef
from app.pricing import Pricing
from app.review_types import Clause
from app.store import JsonStore
from tests.review_helpers import FIXTURES, ScriptedProvider, auditor, capture_page, merchant, mock_text, run_review
from tests.story_helpers import add_user, alerts, audit, subscribe

RISKY_MISSED_BY_BASIC = {"NOTICE_PERIOD", "INTRO_PRICE_STEP_UP", "HARD_CANCEL"}


def quillnote(settings: Settings, store: JsonStore, provider: object | None = None):  # type: ignore[no-untyped-def]
    cap = capture_page(settings, "/shop/quillnote")
    return cap, run_review(store, provider or MockProvider(FIXTURES, Pricing()), cap, "quillnote-plus",
                           fair_trial=False)


# ---- A1 -----------------------------------------------------------------------------------------------------
def test_quillnote_pages_hide_the_traps_in_prose(client: TestClient) -> None:
    page, terms = client.get("/shop/quillnote").text, client.get("/shop/quillnote/terms").text
    for text in (page, terms):
        assert "Fictional merchant for the SubGuard demo." in text
        assert "Note to AI" not in text and "display:none" not in text  # no injection line (Penwright covers it)
    assert "seventy-two hours before your renewal" in terms and "72" not in terms  # notice in words only
    assert "contact our account team" in page and "$27.99 a month" in page  # step-up only in the FAQ
    assert "$27.99" not in terms
    assert client.get("/shop").text.count("shop-merchant-") == 2


def test_quillnote_is_layer2_and_seeded(client: TestClient) -> None:
    store: JsonStore = client.app.state.store  # type: ignore[attr-defined]
    q = next(m for m in store.load("merchants").items if m.id == "quillnote")
    assert not q.fair_trial_member and [p.key for p in q.plans] == ["quillnote-plus"]
    prices = [c.price for c in q.plans[0].billing_cycles]
    assert prices == [Decimal("0.00"), Decimal("12.99"), Decimal("27.99")]


# ---- A2 / A3 ------------------------------------------------------------------------------------------------
def test_ai_finds_what_the_basic_check_misses_on_quillnote(settings: Settings, store: JsonStore) -> None:
    _, data = quillnote(settings, store)
    cmp = data.ai_vs_basic()
    assert cmp is not None and data.basic is not None
    assert len(cmp["ai_only_risky"]) >= 3 and RISKY_MISSED_BY_BASIC <= set(cmp["ai_only_risky"])
    assert "NOTICE_PERIOD" not in data.basic.types
    # deadline from the AI-read notice: "seventy-two hours" -> 3 days -> act by Day 4 (first charge Day 8 - 3 - 1)
    d = data.deadlines
    assert (d.first_charge_day, d.notice_days, d.terms_last_day, d.real_cancel_deadline_day) == (8, 3, 5, 4)
    assert data.notice_source == "quote_words" and d.layer2 and d.timer_fire_day == 2
    assert (data.basic.notice_days, data.basic.real_cancel_deadline_day) == (0, 7)  # basic: too late
    assert data.risk_score > data.basic.risk_score


def test_penwright_basic_check_is_stored_and_matches(settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    data = run_review(store, MockProvider(FIXTURES, Pricing()), cap, "penwright-pro")
    cmp = data.ai_vs_basic()
    assert data.basic is not None and cmp is not None and not cmp["ai_only_risky"]
    assert data.basic.notice_days == 3 and data.notice_source == "quote_digits"


def test_notice_in_words_parsed_by_code() -> None:
    assert duration_days("no later than seventy-two hours before your renewal") == 3
    assert duration_days("at least 3 days before") == 3 and duration_days("two weeks before") == 14
    assert duration_days("forty-nine hours") == 3 and duration_days("before renewal") is None
    assert number_words(72) == "seventy-two" and number_words(7) == "seven"


def _clause(quote: str) -> Clause:
    return Clause(type="NOTICE_PERIOD", quote=quote, plain_english="x")


def test_ai_notice_days_only_with_a_verified_duration_quote() -> None:
    nd = Auditor._notice_days
    assert nd([_clause("Tell us by the third day before renewal.")], 3) == (3, "ai")  # words code can't read
    assert nd([_clause("Write to us no later than seventy-two hours before renewal.")], 9) == (3, "quote_words")
    assert nd([_clause("Write to us before renewal.")], 5) == (0, "none")  # no duration in the quote
    assert nd([], 5) == (0, "none")  # the AI's number alone is never enough


def test_quillnote_quotes_must_still_be_verbatim(settings: Settings, store: JsonStore) -> None:
    bad = json.loads(mock_text("quillnote"))
    bad["clauses"][0]["quote"] = "We need written notice 72 hours before renewal."  # not on the page
    _, data = quillnote(settings, store, ScriptedProvider(json.dumps(bad)))
    assert "NOTICE_PERIOD" not in data.types() and data.deadlines.notice_days == 0


def test_evidence_page_shows_ai_vs_basic(client: TestClient) -> None:
    q = subscribe(client, "quillnote", "quillnote-plus")
    page = client.get(f"/subscriptions/{q['id']}?user=priya").text
    assert 'data-testid="ai-vs-basic"' in page and "Only the AI found" in page
    assert 'data-testid="avb-row-notice_period"' in page and "✗ missed" in page and "(too late)" in page
    p = subscribe(client)
    assert "finds the same things as the AI review" in client.get(f"/subscriptions/{p['id']}?user=priya").text


# ---- A4 -----------------------------------------------------------------------------------------------------
def honest_capture(settings: Settings) -> PageCapture:
    html = (ROOT_DIR / "tests" / "fixtures" / "honest_terms.html").read_text(encoding="utf-8")
    parser = StaticCapture(None, ROOT_DIR / "shop" / "static" / "shop.css").parse(html, "/shop/plainpad")
    return PageCapture(url="/shop/plainpad", merchant_id="plainpad", blocks=parser.blocks,
                       checkboxes=parser.checkboxes)


def test_score_calibration(settings: Settings, store: JsonStore) -> None:
    pen = run_review(store, MockProvider(FIXTURES, Pricing()), capture_page(settings, "/shop/penwright"),
                     "penwright-pro")
    _, quill = quillnote(settings, store)
    assert 80 <= pen.risk_score <= 92 and abs(pen.risk_score - 87) <= 5
    assert 70 <= quill.risk_score <= 90
    assert pen.risk.style_points == {"hard_to_read": 10}  # small grey text counted once
    cap = honest_capture(settings)
    honest_ai = json.dumps({"summary": "A clear monthly plan.", "first_charge_day": 0, "first_charge_amount": "9.99",
                            "notice_days": None, "clauses": [
                                {"type": "AUTO_RENEW",
                                 "quote": "Your plan renews each month at $9.99 until you cancel.",
                                 "plain_english": "It renews monthly.", "money_impact_usd_year": None,
                                 "deadline_day": None, "severity": 1, "evidence_testid": "honest-renewal"}]})
    plan = PlanView(id="P-plainpad", name="Plainpad Basic", currency="USD", billing_cycles=[
        BillingCycleDef(tenure_type="REGULAR", price=Decimal("9.99"), interval_unit="MONTH", interval_count=1,
                        total_cycles=0)])
    honest = asyncio.run(auditor(store, ScriptedProvider(honest_ai)).review(
        cap, plan, merchant=merchant(store, "penwright").model_copy(update={"id": "plainpad"}),
        plan_key=None, signup_day=0, user_id="priya"))
    assert honest.risk_score <= 25 and "TERMS_MISMATCH" not in honest.types()


# ---- A5 -----------------------------------------------------------------------------------------------------
def _cancel(client: TestClient, sub_id: str, user: str = "priya") -> dict:  # type: ignore[type-arg]
    card = client.post("/api/agent/propose", json={"user_id": user, "subscription_ids": [sub_id],
                                                   "reason": "test"}).json()
    return client.post("/api/agent/confirm", json={"user_id": user, "token": card["token"],
                                                   "subscription_ids": [sub_id]}).json()


def test_layer2_cancel_hands_off_then_watches_paypal(client: TestClient) -> None:
    q = subscribe(client, "quillnote", "quillnote-plus")
    out = _cancel(client, q["id"])
    r = out["results"][0]
    assert r["outcome"] == "action_needed" and r["notice_id"] and not r["ok"]  # SubGuard made no PayPal write
    card = alerts(client, kind="action_needed")[0]
    assert card["title"].startswith("ACTION NEEDED")
    assert any(a.get("url") == "/demo/paypal-autopay" for a in card["actions"])
    me = client.get("/me?user=priya").text
    assert 'data-testid="action-needed"' in me and 'data-testid="layer2-waiting"' in me
    assert client.post(f"/api/subscriptions/{q['id']}/check-paypal?user=priya").json()["status"] == "ACTIVE"

    assert "Quillnote" in client.get("/demo/paypal-autopay?user=priya").text
    assert client.post("/api/demo/paypal-autopay/cancel",
                       json={"user_id": "priya", "subscription_id": q["id"]}).json()["status"] == "CANCELLED"
    seen = client.post(f"/api/subscriptions/{q['id']}/check-paypal?user=priya").json()
    assert seen["cancelled"]
    assert 'data-testid="action-needed"' not in client.get("/me?user=priya").text
    done = alerts(client, kind="cancelled")
    assert done and done[0]["title"] == "PayPal shows Quillnote CANCELLED. You won't be charged."
    assert audit(client, "paypal_autopay_cancel", actor="user") and audit(client, "layer2_cancel_seen")
    assert not audit(client, "paypal_call", subscription_id=q["id"], result="cancel")  # no SubGuard cancel write


def test_layer2_check_and_autopay_are_owner_only(client: TestClient) -> None:
    q = subscribe(client, "quillnote", "quillnote-plus")
    other = add_user(client)
    res = client.post(f"/api/subscriptions/{q['id']}/check-paypal?user={other}")
    assert res.status_code == 403 and res.json()["rule_id"] == "R5"
    res = client.post("/api/demo/paypal-autopay/cancel", json={"user_id": other, "subscription_id": q["id"]})
    assert res.status_code == 403


# ---- A6 -----------------------------------------------------------------------------------------------------
def test_no_mock_labels_on_user_surfaces(client: TestClient) -> None:
    q = subscribe(client, "quillnote", "quillnote-plus")
    _cancel(client, q["id"])
    pages = [client.get(u).text for u in ("/", "/me?user=priya", f"/subscriptions/{q['id']}?user=priya",
                                          "/shop/quillnote", "/shop/penwright")]
    for text in pages:
        visible = text.split("<script", 1)[0]
        for word in ("Mock mode", "AI: mock", "fixtures", "mock · ", "Mock PayPal"):
            assert word not in visible
    assert "Demo data" in pages[1]
    notes = client.get("/api/notices?user=priya").json()
    assert notes and notes[0]["merchant_name"] == "Quillnote"

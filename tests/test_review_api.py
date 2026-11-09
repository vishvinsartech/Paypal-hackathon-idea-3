"""Capture + /api/review/preflight + companion wiring on the shop pages."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from tests.review_helpers import capture_page
from tests.test_checkout import buy


def test_static_capture_sees_the_tricks(settings: Settings) -> None:
    cap = capture_page(settings, "/shop/penwright")
    fine = next(b for b in cap.blocks if b.testid == "shop-fineprint")
    assert fine.font_px == 9 and fine.contrast < 3
    hidden = {b.testid: b.hidden_reason for b in cap.blocks if b.hidden}
    assert hidden.get("tos-hidden") == "display:none" and hidden.get("shop-terms-body") == "collapsed"
    assert cap.linked_pages == ["/shop/penwright/terms"]
    assert [c.checked for c in cap.checkboxes if c.testid == "shop-addon"] == [True]
    assert "Simulates the SubGuard browser extension" not in cap.full_text  # our own note is ignored


def test_preflight_penwright(client: TestClient) -> None:
    res = client.post("/api/review/preflight", json={"merchant_url": "http://127.0.0.1:8000/shop/penwright",
                                                     "plan_key": "penwright-pro"})
    assert res.status_code == 200
    body = res.json()
    assert abs(body["risk_score"] - 87) <= 5 and body["deadlines"]["real_cancel_deadline_day"] == 7
    assert {"NOTICE_PERIOD", "TERMS_MISMATCH", "PROMPT_INJECTION_ATTEMPT"} <= {c["type"] for c in body["clauses"]}
    assert body["review_id"] in [r["id"] for r in client.get("/api/reviews?merchant=penwright").json()]
    events = [e["event"] for e in client.get("/api/audit-log").json()]
    assert {"llm_call", "review_run", "prompt_injection_flagged"} <= set(events)


def test_preflight_by_plan_id_and_lumen(client: TestClient) -> None:
    body = client.post("/api/review/preflight", json={"merchant_url": "/shop/lumen",
                                                      "plan_id": "P-MOCK-LUMEN_MONTHLY"}).json()
    assert abs(body["risk_score"] - 15) <= 5 and body["plan_key"] == "lumen-monthly"


def test_preflight_rejects_other_urls(client: TestClient) -> None:
    assert client.post("/api/review/preflight", json={"merchant_url": "https://evil.example/x"}).status_code == 400
    assert client.post("/api/review/preflight", json={"merchant_url": "/shop/nobody"}).status_code == 404
    assert client.post("/api/review/preflight", json={"merchant_url": "/shop/lumen",
                                                      "plan_key": "penwright-pro"}).status_code == 404


def test_register_links_the_preflight_review(client: TestClient) -> None:
    review_id = client.post("/api/review/preflight", json={"merchant_url": "/shop/penwright"}).json()["review_id"]
    created = client.post("/api/checkout/create", json={"merchant_id": "penwright", "plan_key": "penwright-pro",
                                                        "user_id": "priya"}).json()
    client.post("/api/checkout/mock-approve", json={"paypal_id": created["paypal_id"]})
    sub = client.post("/api/subscriptions/register", json={
        "paypal_id": created["paypal_id"], "merchant_id": "penwright", "plan_key": "penwright-pro",
        "user_id": "priya", "review_id": review_id}).json()
    review = client.get(f"/api/reviews/{review_id}").json()
    assert review["subscription_id"] == sub["id"]
    _, other = buy(client, plan_key="lumen-monthly", merchant="lumen")
    assert other.status_code == 200  # type: ignore[attr-defined]


def test_shop_pages_load_the_companion(client: TestClient) -> None:
    for page in ("penwright", "framewise", "lumen"):
        html = client.get(f"/shop/{page}").text
        assert "/static/companion.js" in html and "Simulates the SubGuard browser extension" in html
    assert "companion-overlay" in client.get("/static/companion.js").text

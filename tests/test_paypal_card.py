"""The "Subscribed via PayPal ✓" card (D-113): status/plan/cycles read live from PayPal, audited with debug ids.

Mock mode here (the mock PayPal is the "live" source); the real sandbox path is scripts/sandbox_ui_check.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.integrations.paypal_types import debug_header
from tests.story_helpers import add_user, advance_to, alerts, audit, cancel_via_alert, subscribe

CYCLES = ["10-day trial $0", "3 × $24.99/month", "then $49.99/month"]


def card(c: TestClient, sub_id: str, user: str = "usera") -> dict:
    res = c.get(f"/api/subscriptions/{sub_id}/paypal?user={user}")
    assert res.status_code == 200, res.text
    return res.json()


def test_card_reads_status_and_cycles_from_paypal(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    got = card(c, main["id"])
    assert got["ok"] and got["status"] == "ACTIVE" and got["paypal_id"] == main["paypal_id"]
    assert got["plan_name"] == "Penwright Pro" and [x["text"] for x in got["cycles"]] == CYCLES
    assert [(x["tenure_type"], x["price"], x["total_cycles"]) for x in got["cycles"]] == [
        ("TRIAL", "0.00", 1), ("TRIAL", "24.99", 3), ("REGULAR", "49.99", 0)]
    assert got["debug_id"].startswith("mock-") and got["matches_local"] and got["cancel"] is None
    assert got["created"]["request_id"].startswith("subguard-create-")  # our server created it
    assert got["autopay_url"] is None and "Mock PayPal" in got["source"]  # the sandbox link is sandbox-only
    (row,) = audit(c, "paypal_subscription_verified")
    assert row["paypal_debug_id"] == got["debug_id"] and row["status_after"] == "ACTIVE"
    assert row["paypal_request_id"] == got["created"]["request_id"]
    assert row["details"]["plan_debug_id"] == got["plan_debug_id"]


def test_status_is_live_not_assumed(demo_client: TestClient) -> None:
    """If PayPal and our copy disagree, the card shows PayPal's status and says so."""
    c = demo_client
    main = subscribe(c)
    svc = c.app.state.services  # type: ignore[attr-defined]
    with svc.store.edit("mock_paypal") as state:  # PayPal's side changes behind SubGuard's back
        state.subscriptions[main["paypal_id"]].status = "SUSPENDED"
    got = card(c, main["id"])
    assert got["status"] == "SUSPENDED" and got["local_status"] == "ACTIVE" and not got["matches_local"]


def test_after_cancel_same_id_shows_cancelled_with_the_cancel_ids(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    got = card(c, main["id"])
    assert got["paypal_id"] == main["paypal_id"] and got["status"] == "CANCELLED"
    cancel_row = audit(c, "paypal_cancel")[-1]
    assert got["cancel"]["request_id"] == cancel_row["paypal_request_id"]
    assert got["cancel"]["debug_id"] == cancel_row["paypal_debug_id"] and got["cancel"]["debug_id"].startswith("mock-")
    assert audit(c, "paypal_subscription_verified")[-1]["paypal_request_id"] == cancel_row["paypal_request_id"]


def test_card_is_owner_only(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    add_user(c)
    res = c.get(f"/api/subscriptions/{main['id']}/paypal?user=intruder")
    assert res.status_code == 403 and res.json()["rule_id"] == "R5"


def test_paypal_error_gives_a_friendly_card(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    c.app.state.services.gw.mock.inject_failure("get_subscription", status=503)  # type: ignore[attr-defined]
    got = card(c, main["id"])
    assert not got["ok"] and "Couldn't reach PayPal" in got["error"]
    assert audit(c, "paypal_subscription_verified")[-1]["result"].startswith("error:")


def test_pages_host_the_card_and_mock_label(client: TestClient) -> None:
    for url, host in (("/?demo=1", 'id="pp-demo"'), ("/user", 'id="pp-user"')):
        html = client.get(url).text
        assert host in html and "data-paypal-cards" in html and "/static/paypal-card.js" in html
    shop = client.get("/shop/penwright").text
    assert "Mock PayPal approval (run in sandbox mode for the real PayPal window)" in shop
    assert "/static/paypal-card.js" in shop
    js = client.get("/static/paypal-card.js").text
    for testid in ("paypal-subscribed", "paypal-status", "paypal-sub-id", "paypal-cycles", "paypal-autopay-link"):
        assert testid in js, testid
    assert "Subscribed via PayPal ✓" in js and "View in PayPal sandbox" in js


@pytest.mark.parametrize(("headers", "expected"), [
    ({"Paypal-Debug-Id": "abc123"}, "abc123"), ({"paypal-debug-id": "x"}, "x"), ({}, None), (None, None)])
def test_debug_header_any_case(headers: object, expected: str | None) -> None:
    assert debug_header(headers) == expected

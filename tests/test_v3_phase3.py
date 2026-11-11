"""FIX_PLAN Phase 3 backend pieces: the companion verdict (U14-U16), the confirm card's next charge (U12), the email
app path (U13), routine PayPal reads (U26), vendored libraries (U30)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import ROOT_DIR
from tests.story_helpers import advance_to, alerts, cancel_via_alert, on, subscribe


def preflight(c: TestClient, merchant: str = "penwright", plan: str = "penwright-pro") -> dict:
    body = {"merchant_url": f"/shop/{merchant}", "plan_key": plan, "user_id": "priya"}
    r = c.post("/api/review/preflight", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_companion_verdict_from_the_paypal_plan(demo_client: TestClient) -> None:
    v = preflight(demo_client)["display"]["verdict"]
    assert v["line"] == f"$0 today, then $24.99/month from {on(11)}"
    assert v["sub"] == "Rises to $49.99 after 3 months · up to $524.88 in year one"
    assert v["paypal_line"] == f"The page says $0 today. The PayPal plan charges $24.99 on {on(11)}."
    assert v["paypal_warn"]
    assert [t["type"] for t in v["things"]] == ["NOTICE_PERIOD", "HARD_CANCEL", "EARLY_TRIAL_TERMINATION"]
    assert all("_" not in t["label"] for t in v["things"])  # plain labels, never the enum
    quotes = [" ".join(q["quote"].split()).lower() for q in v["quotes"]]
    assert len(quotes) == len(set(quotes)) and v["evidence_label"] == f"{len(quotes)} quoted clauses, cross-check table"
    assert not v["rows"][0]["match"] and v["rows"][0]["label"].startswith("The headline says")  # U16: fail first
    assert "Price $24.99 shown only in fine print" in [r["label"] for r in v["rows"]]
    q = preflight(demo_client, "quillnote", "quillnote-plus")
    assert q["risk_score"] == 73 and q["display"]["verdict"]["things"][0]["type"] == "NOTICE_PERIOD"


def test_shop_redesign_keeps_the_scores(demo_client: TestClient) -> None:
    """U20 changed the markup, not the scored text: Penwright 87, Quillnote 73 (D-143)."""
    assert preflight(demo_client)["risk_score"] == 87
    assert preflight(demo_client, "quillnote", "quillnote-plus")["risk_score"] == 73


def test_confirm_card_says_the_charge_it_avoids(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    card = c.post("/api/agent/propose", json={"user_id": "priya", "subscription_ids": [main["id"]],
                                              "reason": "test"}).json()
    (item,) = card["items"]
    assert (item["short_name"], item["trial"], item["next_charge_text"]) == ("Penwright", True, f"$24.99 on {on(11)}")
    assert "/yr" not in (ROOT_DIR / "app" / "static" / "app.js").read_text(encoding="utf-8").split(
        "function cardHtml", 1)[1].split("function showCard", 1)[0]


def test_open_in_my_email_app(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    n = c.get("/api/notices?user=priya").json()[0]
    assert n["clause"] and n["clause"] in n["body"]  # U13: the quoted clause, for the highlight
    out = c.post(f"/api/notices/{n['id']}/mailto", json={"user_id": "priya", "to": n["to"], "subject": n["subject"],
                                                         "body": n["body"]}).json()
    assert out["notice"]["sent_via"] == "mailto" and out["notice"]["status"] == "sent"
    texts = [a["text"] for a in c.get("/api/activity?user=priya").json()]
    assert "You opened the cancellation email in your email app (edited: no)." in texts
    assert "Opened in your email app (demo)" in c.get("/").text


def test_routine_paypal_reads_are_tagged(demo_client: TestClient) -> None:
    """U26: successful PayPal reads carry details.routine (still hash-chained); writes never do."""
    c = demo_client
    main = subscribe(c)
    c.get(f"/api/subscriptions/{main['id']}/paypal?user=priya")
    calls = [e for e in c.get("/api/audit-log").json() if e["event"] == "paypal_call"]
    reads = [e for e in calls if e["details"]["op"] in ("get_plan", "verify_subscription", "verify_plan")]
    writes = [e for e in calls if e["details"]["op"] in ("create_subscription",)]
    assert reads and all(e["details"].get("routine") is True for e in reads)
    assert writes and not any(e["details"].get("routine") for e in writes)
    assert c.get("/api/audit-log/verify").json()["ok"]


def test_vendored_libraries(client: TestClient) -> None:
    """U30: AG Grid 36.2.0 and AG Charts 14.2.0 served from /static/vendor, licence files kept."""
    vendor = ROOT_DIR / "app" / "static" / "vendor"
    for name in ("ag-grid-community-36.2.0.min.js", "ag-charts-community-14.2.0.min.js"):
        assert client.get(f"/static/vendor/{name}").status_code == 200
    for lic in ("ag-grid-community-LICENSE.txt", "ag-charts-community-LICENSE.txt"):
        assert "MIT License" in (vendor / lic).read_text(encoding="utf-8")

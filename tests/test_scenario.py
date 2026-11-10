"""Milestone 7: Story A (Priya) and Story B (John) end to end on ONE shared sim timeline, in mock mode, through the
same HTTP API the UI uses (shop checkout, alert buttons, chat, confirm). Asserts the $872.76 KPI."""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from tests.story_helpers import advance_to, alerts, audit, cancel_via_alert, sub, subscribe


def chat(c: TestClient, message: str, user: str) -> tuple[str, list[dict[str, Any]]]:
    res = c.post("/api/chat", json={"user_id": user, "message": message})
    events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
    answer = " ".join(e["text"] for e in events if e["type"] == "text")
    return answer, [e["card"] for e in events if e["type"] == "card"]


def test_story_a_and_b_end_to_end(demo_client: TestClient) -> None:
    c = demo_client
    # ---- Day 0 ------------------------------------------------------------------------------------------------
    pre = c.post("/api/review/preflight", json={"merchant_url": "/shop/penwright", "plan_key": "penwright-pro"}).json()
    assert abs(pre["risk_score"] - 87) <= 5 and pre["deadlines"]["real_cancel_deadline_day"] == 7
    assert {"NOTICE_PERIOD", "TERMS_MISMATCH", "PROMPT_INJECTION_ATTEMPT"} <= {cl["type"] for cl in pre["clauses"]}
    main, addon = subscribe(c, "penwright", "penwright-pro", addon_key="penwright-ai-pack")
    assert addon is not None
    _, done = cancel_via_alert(c, alerts(c, kind="addon_offer")[0], action="remove_addon")
    assert done["all_ok"] and sub(c, addon["id"])["status"] == "CANCELLED"
    assert "I'll cancel Penwright on Day 6" in alerts(c, kind="timer_set")[0]["body"]

    lumen = c.get("/api/subscriptions?user=john").json()[0]
    lumen_review = c.get(f"/api/reviews?subscription_id={lumen['id']}").json()[0]
    assert abs(lumen_review["risk_score"] - 15) <= 5 and c.get("/api/timers?user=john").json() == []

    # ---- Day 5: Priya's reminder --------------------------------------------------------------------------------
    advance_to(c, 5)
    assert alerts(c, kind="reminder")[0]["body"].startswith("Your real deadline is in 2 days.")

    # ---- Day 6: auto-cancel + written notice --------------------------------------------------------------------
    advance_to(c, 6)
    assert sub(c, main["id"])["status"] == "CANCELLED"
    assert c.get("/api/notices?user=priya").json()[0]["to"] == "cancel@penwright.example"

    # ---- Day 10: John asks about yearly; numbers from code, decision left to him ---------------------------------
    advance_to(c, 10)
    answer, cards = chat(c, "Should I switch to yearly?", "john")
    assert "$240 a year" in answer and "$200" in answer and "save $40" in answer
    assert "9 of the last 10 days" in answer and cards == []

    # ---- Day 15: the blocked first charge ---------------------------------------------------------------------
    advance_to(c, 15)
    blocked = [a for a in alerts(c, kind="blocked_charge") if a["subscription_id"] == main["id"]]
    assert blocked[0]["body"] == "First charge due today: blocked. No active PayPal subscription."

    # ---- Day 21: price rise, chat, confirmation card, confirm -------------------------------------------------------
    advance_to(c, 21)
    c.post("/api/demo/price-rise")
    assert [a["label"] for a in alerts(c, kind="price_rise")[0]["actions"]] == ["Keep at $19", "Cancel"]
    answer, cards = chat(c, "Is it still worth it? I barely used it.", "priya")
    assert "You opened it 3 times this month. Keeping it costs $228 a year." in answer
    (card,) = cards
    assert card["total_text"] == "$228/yr"
    done = c.post("/api/agent/confirm", json={"user_id": "priya", "token": card["token"], "subscription_ids":
                                              [i["subscription_id"] for i in card["items"]]}).json()
    assert done["all_ok"]
    reused = c.post("/api/agent/confirm", json={"user_id": "priya", "token": card["token"], "subscription_ids":
                                                [i["subscription_id"] for i in card["items"]]})
    assert reused.status_code == 403 and reused.json()["rule_id"] == "R3"

    # ---- Day 27: John's renewal nudge -> Keep, no PayPal write ----------------------------------------------------
    advance_to(c, 27)
    (renewal,) = alerts(c, user="john", kind="renewal")
    assert renewal["body"] == "Lumen Notes renews in 3 days for $20. You haven't used it for 2 weeks. Keep or cancel?"
    kept = c.post(f"/api/alerts/{renewal['id']}/act", json={"user_id": "john", "action": "keep"}).json()
    assert kept["status"] == "kept"

    # ---- The money and the evidence ---------------------------------------------------------------------------------
    kpi = c.get("/api/kpis?user=priya").json()
    assert Decimal(kpi["money_protected"]) == Decimal("872.76") and kpi["money_protected_text"] == "$872.76"
    assert kpi["subscriptions_cancelled"] == 3
    assert Decimal(c.get("/api/kpis?user=john").json()["money_protected"]) == Decimal("0")
    assert sub(c, lumen["id"], user="john")["status"] == "ACTIVE" and not audit(c, "paypal_cancel", user_id="john")

    cancels = audit(c, "paypal_cancel", result="ok")
    assert sorted((r["actor"], r["rule_id"]) for r in cancels) == [("timer", "R2"), ("user", "R1"), ("user", "R1")]
    for r in cancels:  # every cancel has an allowed policy decision with the same rule id (definition of done)
        assert audit(c, "policy_decision", subscription_id=r["subscription_id"], rule_id=r["rule_id"],
                     decision="allowed", actor="policy")
    assert c.get("/api/audit-log/verify").json()["ok"]
    rows = list(csv.DictReader(io.StringIO(c.get("/api/audit-log.csv").text)))
    assert len(rows) == len(c.get("/api/audit-log").json()) and {"paypal_cancel", "chat_tool_call"} <= {
        r["event"] for r in rows}

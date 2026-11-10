"""Milestone 7: the demo story end to end in mock mode, through the same HTTP API the UI uses (shop checkout,
alert buttons, chat, confirm). Priya asks the chat whether to keep Penwright, then cancels with confirmation.
Asserts the $524.88 "Money protected" KPI."""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from tests.story_helpers import advance_to, alerts, audit, sub, subscribe


def chat(c: TestClient, message: str, user: str = "priya") -> tuple[str, list[dict[str, Any]]]:
    res = c.post("/api/chat", json={"user_id": user, "message": message})
    events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
    answer = " ".join(e["text"] for e in events if e["type"] == "text")
    return answer, [e["card"] for e in events if e["type"] == "card"]


def test_story_end_to_end_with_chat(demo_client: TestClient) -> None:
    c = demo_client
    # ---- Day 0: the companion reads the fine print, Priya approves --------------------------------------------
    pre = c.post("/api/review/preflight", json={"merchant_url": "/shop/penwright", "plan_key": "penwright-pro"}).json()
    assert abs(pre["risk_score"] - 87) <= 5 and pre["deadlines"]["real_cancel_deadline_day"] == 7
    assert {"NOTICE_PERIOD", "TERMS_MISMATCH", "PROMPT_INJECTION_ATTEMPT"} <= {cl["type"] for cl in pre["clauses"]}
    main = subscribe(c)
    assert alerts(c, kind="timer_set")[0]["title"] == "I'll check with you before your trial runs out."

    # ---- Day 5: the check-in, then Priya asks the chat ----------------------------------------------------------
    advance_to(c, 5)
    assert alerts(c, kind="reminder")[0]["body"].startswith("Your Penwright trial is ending.")
    answer, cards = chat(c, "Should I keep Penwright?")
    assert "You've opened Penwright Studio twice so far." in answer
    assert "the first paid year costs $524.88" in answer and "Day 7" in answer and cards == []
    assert not audit(c, "paypal_cancel")  # advice only

    answer, cards = chat(c, "Cancel Penwright")
    (card,) = cards
    assert card["total_text"] == "$524.88/yr" and "Nothing happens until you tap Confirm" in answer
    ids = [i["subscription_id"] for i in card["items"]]
    done = c.post("/api/agent/confirm", json={"user_id": "priya", "token": card["token"], "subscription_ids": ids})
    assert done.json()["all_ok"] and sub(c, main["id"])["status"] == "CANCELLED"
    reused = c.post("/api/agent/confirm", json={"user_id": "priya", "token": card["token"], "subscription_ids": ids})
    assert reused.status_code == 403 and reused.json()["rule_id"] == "R3"
    assert alerts(c, kind="cancelled")[0]["title"] == "Done. You won't be charged."
    assert c.get("/api/notices?user=priya").json()[0]["to"] == "cancel@penwright.example"

    # ---- Day 15: the blocked first charge -----------------------------------------------------------------------
    advance_to(c, 15)
    blocked = [a for a in alerts(c, kind="blocked_charge") if a["subscription_id"] == main["id"]]
    assert blocked[0]["body"] == "First charge due today: blocked. No active PayPal subscription."

    # ---- The money and the evidence -----------------------------------------------------------------------------
    kpi = c.get("/api/kpis?user=priya").json()
    assert Decimal(kpi["money_protected"]) == Decimal("524.88") and kpi["money_protected_text"] == "$524.88"
    assert kpi["subscriptions_cancelled"] == 1

    cancels = audit(c, "paypal_cancel", result="ok")
    assert [(r["actor"], r["rule_id"]) for r in cancels] == [("user", "R1")]
    for r in cancels:  # every cancel has an allowed policy decision with the same rule id (definition of done)
        assert audit(c, "policy_decision", subscription_id=r["subscription_id"], rule_id=r["rule_id"],
                     decision="allowed", actor="policy")
    assert c.get("/api/audit-log/verify").json()["ok"]
    rows = list(csv.DictReader(io.StringIO(c.get("/api/audit-log.csv").text)))
    assert len(rows) == len(c.get("/api/audit-log").json()) and {"paypal_cancel", "chat_tool_call"} <= {
        r["event"] for r in rows}

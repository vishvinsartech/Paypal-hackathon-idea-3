"""The demo story (spec 2): userA + Penwright. Day 0 approve -> Day 5 "keep or cancel?" -> Cancel / Keep / no answer
(Day 6 auto-cancel) -> Day 11 blocked charge. Right alerts, actions and audit entries (actors + rule ids)."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from tests.story_helpers import advance_to, alerts, audit, cancel_via_alert, sub, subscribe

DAY5_ASKED = ("Your Penwright trial ends on Day 10, but your real last day to cancel is Day 7. You've opened it twice. "
              "Do you want to keep it?")
DAY5_BODY = DAY5_ASKED + " If I don't hear back, I'll cancel it tomorrow so you're not charged."
BLOCKED = "First charge due today: blocked. No active PayPal subscription."


def day0(c: TestClient) -> dict[str, Any]:
    pre = c.post("/api/review/preflight", json={"merchant_url": "/shop/penwright", "plan_key": "penwright-pro"}).json()
    assert abs(pre["risk_score"] - 87) <= 5 and pre["summary"]
    main = subscribe(c)
    (timer_set,) = alerts(c, kind="timer_set")
    assert timer_set["title"] == "I'll check with you before your trial runs out."
    assert timer_set["body"] == ("Your real last day to cancel Penwright is Day 7; the first charge is Day 11. "
                                 "I'll ask you on Day 5. If I don't hear back, I'll cancel Penwright on Day 6 "
                                 "so you're not charged.")
    timer = next(t for t in c.get("/api/timers?user=usera").json() if t["subscription_id"] == main["id"])
    assert (timer["fire_day"], timer["deadline_day"], timer["reminder_day"], timer["billing_day"]) == (6, 7, 5, 11)
    assert timer["shown_to_user"] and timer["status"] == "PENDING"
    assert audit(c, "timer_created", rule_id="R2", subscription_id=main["id"])
    return main


def day5(c: TestClient) -> dict[str, Any]:
    advance_to(c, 5)
    (check,) = alerts(c, kind="reminder")
    assert check["title"] == "Penwright: keep it or cancel?" and check["body"] == DAY5_BODY
    assert [(a["action"], a["label"]) for a in check["actions"]] == [("keep", "Keep"), ("cancel", "Cancel")]
    assert check["delivery"] == {"in_app": "shown", "email": "mocked", "sms": "mocked"}  # Zapier email + SMS
    assert audit(c, "timer_warned", actor="timer", rule_id="R2", result="zapier_mocked")
    return check


def assert_done(c: TestClient, sub_id: str, by: str) -> None:
    """PayPal cancelled first, then a DRAFT email (never sent without userA's click)."""
    s = sub(c, sub_id)
    assert s["status"] == "CANCELLED" and s["cancelled_by"] == by
    notice = next(n for n in c.get("/api/notices?user=usera").json() if n["subscription_id"] == sub_id)
    assert notice["to"] == "cancel@penwright.example" and notice["status"] == "draft" and notice["sent_at"] is None
    assert notice["sha256"] == hashlib.sha256(notice["body"].encode()).hexdigest()
    assert notice["drafted_by"] == "mock · fixtures" and notice["draft_problems"] == []
    assert "at least 3 days before the next billing date" in notice["body"]
    rows = audit(c)
    seq = {r["event"]: r["seq"] for r in rows if r.get("subscription_id") == sub_id}
    assert seq["paypal_cancel"] < seq["cancellation_email_drafted"]  # PayPal first, then the email
    assert not audit(c, "cancellation_email_sent")
    (done,) = alerts(c, kind="cancelled")
    assert done["title"] == "Cancelled in PayPal. You won't be charged."
    assert "Your cancellation email is ready to review and send." in done["body"]
    assert [a["action"] for a in done["actions"]] == ["review_email"]  # no Restart trial button
    assert done["actions"][0]["notice_id"] == notice["id"]


def assert_day11_blocked(c: TestClient, sub_id: str) -> None:
    advance_to(c, 11)
    blocked = [a for a in alerts(c, kind="blocked_charge") if a["subscription_id"] == sub_id]
    assert blocked and blocked[0]["body"] == BLOCKED
    assert audit(c, "charge_blocked", subscription_id=sub_id)
    kpi = c.get("/api/kpis?user=usera").json()
    assert Decimal(kpi["money_protected"]) == Decimal("524.88") and kpi["money_protected_text"] == "$524.88"
    assert kpi["subscriptions_cancelled"] == 1
    assert c.get("/api/audit-log/verify").json()["ok"]


def test_cancel_on_day5(demo_client: TestClient) -> None:
    """The demo path: userA taps Cancel on the Day 5 check-in and confirms."""
    c = demo_client
    main = day0(c)
    check = day5(c)
    card, done = cancel_via_alert(c, check)
    assert card["total_text"] == "$524.88/yr" and "can't be undone" in card["warning"]
    assert done["all_ok"] and done["results"][0]["outcome"] == "cancelled"
    assert audit(c, "policy_decision", subscription_id=main["id"], rule_id="R1", decision="allowed", actor="policy")
    assert audit(c, "paypal_cancel", subscription_id=main["id"], actor="user", rule_id="R1", result="ok")
    assert audit(c, "confirm_token_used", rule_id="R3")
    assert_done(c, main["id"], "user")
    advance_to(c, 6)  # the timer stood down: no second cancel
    assert not audit(c, "timer_fired")
    assert_day11_blocked(c, main["id"])


def test_no_answer_auto_cancels_on_day6(demo_client: TestClient) -> None:
    """No answer by Day 6: R2 allows the auto-cancel (shown on Day 0, warned on Day 5)."""
    c = demo_client
    main = day0(c)
    day5(c)
    assert sub(c, main["id"])["status"] == "ACTIVE"
    advance_to(c, 6)
    assert sub(c, main["id"])["cancelled_day"] == 6
    assert audit(c, "policy_decision", subscription_id=main["id"], rule_id="R2", decision="allowed", actor="policy")
    assert audit(c, "timer_fired", actor="timer", rule_id="R2", subscription_id=main["id"])
    assert audit(c, "paypal_cancel", actor="timer", rule_id="R2", subscription_id=main["id"], result="ok",
                 status_after="CANCELLED")
    assert_done(c, main["id"], "timer")
    keep_late = c.post(f"/api/subscriptions/{main['id']}/keep", json={"user_id": "usera"}).json()
    assert keep_late["status"] == "too_late"  # corner case 11
    assert_day11_blocked(c, main["id"])


def test_keep_on_day5_means_no_more_prompts(demo_client: TestClient) -> None:
    c = demo_client
    main = day0(c)
    check = day5(c)
    res = c.post(f"/api/alerts/{check['id']}/act", json={"user_id": "usera", "action": "keep"}).json()
    assert res["status"] == "kept"
    s = sub(c, main["id"])
    assert s["status"] == "ACTIVE" and s["kept_day"] == 5
    assert all(t["status"] == "KEPT" for t in c.get("/api/timers?user=usera").json())
    assert audit(c, "timer_kept", actor="user", subscription_id=main["id"])
    before = {a["id"] for a in alerts(c)}
    advance_to(c, 11)
    assert sub(c, main["id"])["status"] == "ACTIVE"
    assert {a["id"] for a in alerts(c)} == before  # no further prompts, no blocked-charge claim
    assert not audit(c, "paypal_cancel")
    assert all(a["acknowledged_at"] for a in alerts(c) if a["actions"])
    assert Decimal(c.get("/api/kpis?user=usera").json()["money_protected"]) == Decimal("0")


def test_jump_is_idempotent(demo_client: TestClient) -> None:
    """Corner case 14: jumping 0 -> 11 in one go gives the same alerts as stepping, with no duplicates."""
    c = demo_client
    day0(c)
    advance_to(c, 11)
    advance_to(c, 11)
    kinds = [a["kind"] for a in alerts(c)]
    assert kinds.count("reminder") == 1 and kinds.count("cancelled") == 1 and kinds.count("blocked_charge") == 1
    assert len({a["idempotency_key"] for a in alerts(c)}) == len(alerts(c))

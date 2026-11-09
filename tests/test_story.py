"""Milestone 5 check: Story A (Priya) days 0 -> 5 -> 6 -> 15 -> 21 and Story B (John) days 0 -> 10 -> 27,
with the right alerts, actions and audit entries (actors + rule ids). Mock mode, demo seed on."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.savings import compare_billing
from app.core.usage import days_used
from tests.review_helpers import plan_for
from tests.story_helpers import advance_to, alerts, audit, cancel_via_alert, sub, subscribe


def story_a_day0(c: TestClient) -> tuple[dict, dict]:
    main, addon = subscribe(c, "penwright", "penwright-pro", addon_key="penwright-ai-pack")
    assert addon is not None
    return main, addon


def test_story_a(demo_client: TestClient) -> None:
    c = demo_client
    # ---- Day 0: approval, add-on offer, safety timer shown -------------------------------
    main, addon = story_a_day0(c)
    offer = alerts(c, kind="addon_offer")
    assert len(offer) == 1 and offer[0]["title"] == "Remove the $9.99 add-on you didn't pick?"
    timer_alert = alerts(c, kind="timer_set")[0]
    assert "I'll cancel Penwright on Day 6 unless you tell me to keep it." in timer_alert["body"]
    timer = next(t for t in c.get("/api/timers?user=priya").json() if t["subscription_id"] == main["id"])
    assert (timer["fire_day"], timer["deadline_day"], timer["reminder_day"], timer["billing_day"]) == (6, 7, 5, 15)
    assert timer["shown_to_user"] and timer["status"] == "PENDING"

    card, done = cancel_via_alert(c, offer[0], action="remove_addon")
    assert Decimal(card["total_per_year"]) == Decimal("119.88") and "can't be undone" in card["warning"]
    assert done["all_ok"] and done["results"][0]["outcome"] == "cancelled"
    assert sub(c, addon["id"])["status"] == "CANCELLED"
    assert audit(c, "policy_decision", subscription_id=addon["id"], rule_id="R1", decision="allowed", actor="policy")
    assert audit(c, "paypal_cancel", subscription_id=addon["id"], actor="user", rule_id="R1", result="ok")
    assert audit(c, "confirm_token_used", rule_id="R3")

    # ---- Day 5: reminder on every channel -----------------------------------------------
    advance_to(c, 5)
    reminder = alerts(c, kind="reminder")
    assert len(reminder) == 1
    assert reminder[0]["body"] == ("Your real deadline is in 2 days. You've opened Penwright twice. "
                                   "I'll cancel it tomorrow unless you tap Keep.")
    assert reminder[0]["delivery"] == {"in_app": "shown", "email": "mocked", "sms": "mocked"}
    assert audit(c, "timer_warned", actor="timer", rule_id="R2", result="zapier_mocked")
    assert sub(c, main["id"])["status"] == "ACTIVE"

    # ---- Day 6: SubGuard acts --------------------------------------------------------------
    advance_to(c, 6)
    s = sub(c, main["id"])
    assert s["status"] == "CANCELLED" and s["cancelled_by"] == "timer" and s["cancelled_day"] == 6
    assert audit(c, "policy_decision", subscription_id=main["id"], rule_id="R2", decision="allowed", actor="policy")
    assert audit(c, "timer_fired", actor="timer", rule_id="R2", subscription_id=main["id"])
    assert audit(c, "paypal_cancel", actor="timer", rule_id="R2", subscription_id=main["id"], result="ok",
                 status_after="CANCELLED")
    notice = next(n for n in c.get("/api/notices?user=priya").json() if n["subscription_id"] == main["id"])
    assert notice["to"] == "cancel@penwright.example"
    assert notice["sha256"] == hashlib.sha256(notice["body"].encode()).hexdigest()
    assert audit(c, "cancellation_notice_sent", subscription_id=main["id"])
    done_alert = alerts(c, kind="auto_cancelled")[0]
    assert done_alert["title"] == "Done. You won't be charged."
    assert "Tap here to restart the trial" in done_alert["body"]
    assert [a["action"] for a in done_alert["actions"]] == ["restart"]
    keep_late = c.post(f"/api/subscriptions/{main['id']}/keep", json={"user_id": "priya"}).json()
    assert keep_late["status"] == "too_late"  # corner case 11

    # ---- Day 15: proof -------------------------------------------------------------------
    advance_to(c, 15)
    blocked = [a for a in alerts(c, kind="blocked_charge") if a["subscription_id"] == main["id"]]
    assert blocked and blocked[0]["body"] == "First charge due today: blocked. No active PayPal subscription."
    assert audit(c, "charge_blocked", subscription_id=main["id"])

    # ---- Day 21: the sneaky price rise ------------------------------------------------------
    advance_to(c, 21)
    assert c.post("/api/demo/price-rise").status_code == 200
    assert audit(c, "paypal_call", actor="merchant_sim")
    rise = alerts(c, kind="price_rise")
    assert len(rise) == 1
    assert [a["label"] for a in rise[0]["actions"]] == ["Keep at $19", "Cancel"]
    assert "$228 a year" in rise[0]["body"] and "Day 24" in rise[0]["body"]
    fw = next(s for s in c.get("/api/subscriptions?user=priya").json() if s["merchant_id"] == "framewise")
    card, done = cancel_via_alert(c, rise[0])
    assert card["total_text"] == "$228/yr" and done["all_ok"]
    assert audit(c, "paypal_cancel", actor="user", rule_id="R1", subscription_id=fw["id"], result="ok")
    assert all(t["status"] != "PENDING" for t in c.get("/api/timers?user=priya").json())

    kpi = c.get("/api/kpis?user=priya").json()
    assert Decimal(kpi["money_protected"]) == Decimal("872.76")  # 524.88 + 119.88 + 228.00
    assert kpi["subscriptions_cancelled"] == 3
    assert c.get("/api/audit-log/verify").json()["ok"]


def test_story_a_jump_is_idempotent(demo_client: TestClient) -> None:
    """Corner case 14: jumping 0 -> 21 in one go gives the same alerts as stepping, with no duplicates."""
    c = demo_client
    story_a_day0(c)
    advance_to(c, 21)
    advance_to(c, 21)
    kinds = [a["kind"] for a in alerts(c)]
    assert kinds.count("reminder") == 1 and kinds.count("auto_cancelled") == 1
    assert len({a["idempotency_key"] for a in alerts(c)}) == len(alerts(c))


def test_price_rise_unanswered_auto_cancels_before_billing(demo_client: TestClient) -> None:
    c = demo_client
    advance_to(c, 21)
    c.post("/api/demo/price-rise")
    fw = next(s for s in c.get("/api/subscriptions?user=priya").json() if s["merchant_id"] == "framewise")
    timer = next(t for t in c.get("/api/timers?user=priya").json() if t["kind"] == "price_rise")
    assert timer["fire_day"] == 24 and timer["warning_delivered"] and timer["warned_day"] == 21
    advance_to(c, 24)
    assert sub(c, fw["id"])["status"] == "CANCELLED"
    assert audit(c, "policy_decision", subscription_id=fw["id"], rule_id="R2", decision="allowed")
    assert audit(c, "paypal_cancel", actor="timer", subscription_id=fw["id"], rule_id="R2")


def test_keep_at_new_price_updates_consent(demo_client: TestClient) -> None:
    """Corner case 36: Keep at $19 -> snapshot is $19, timer kept, no more alerts."""
    c = demo_client
    advance_to(c, 21)
    c.post("/api/demo/price-rise")
    rise = alerts(c, kind="price_rise")[0]
    res = c.post(f"/api/alerts/{rise['id']}/act", json={"user_id": "priya", "action": "keep_new_price"}).json()
    assert res["status"] == "kept"
    fw = next(s for s in c.get("/api/subscriptions?user=priya").json() if s["merchant_id"] == "framewise")
    assert Decimal(fw["consent_snapshot"]["price"]) == Decimal("19.00")
    advance_to(c, 26)
    assert sub(c, fw["id"])["status"] == "ACTIVE" and len(alerts(c, kind="price_rise")) == 1


def test_story_b(demo_client: TestClient) -> None:
    c = demo_client
    # ---- Day 0: honest merchant, low risk, consent snapshot, no timer -------------------------
    lumen = c.get("/api/subscriptions?user=john").json()
    assert len(lumen) == 1 and lumen[0]["plan_key"] == "lumen-monthly"
    assert Decimal(lumen[0]["consent_snapshot"]["price"]) == Decimal("20.00")
    review = c.get(f"/api/reviews?subscription_id={lumen[0]['id']}").json()[0]
    assert abs(review["risk_score"] - 15) <= 5 and "CLEAR_TERMS" in {cl["type"] for cl in review["data"]["clauses"]}
    assert c.get("/api/timers?user=john").json() == []
    assert alerts(c, user="john") == []

    # ---- Day 10: monthly vs yearly, from code --------------------------------------------------
    advance_to(c, 10)
    cmp = compare_billing(plan_for("lumen-monthly").billing_cycles, plan_for("lumen-yearly").billing_cycles)
    assert cmp == {"monthly_per_year": Decimal("240.00"), "yearly_per_year": Decimal("200.00"),
                   "yearly_saves": Decimal("40.00")}
    store = c.app.state.store  # type: ignore[attr-defined]
    assert days_used(store, "john", "lumen", 10, 10) == 9
    assert alerts(c, user="john") == []

    # ---- Day 27: renewal reminder; John keeps ----------------------------------------------------
    advance_to(c, 27)
    renewal = alerts(c, user="john", kind="renewal")
    assert len(renewal) == 1
    assert renewal[0]["body"] == ("Lumen Notes renews in 3 days for $20. You haven't used it for 2 weeks. "
                                  "Keep or cancel?")
    res = c.post(f"/api/alerts/{renewal[0]['id']}/act", json={"user_id": "john", "action": "keep"}).json()
    assert res["status"] == "kept"
    assert sub(c, lumen[0]["id"], user="john")["status"] == "ACTIVE"
    assert audit(c, "keep_subscription", actor="user", user_id="john")
    assert not audit(c, "paypal_cancel", user_id="john")

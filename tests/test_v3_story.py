"""v3 Phase 1 story logic. D7: no answer -> the written notice. With the companion's opt-in the Day 6 auto-cancel
also sends the cancellation email (R2, notice_auto_sent); without it, a Day 7 reminder says it isn't sent yet."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.story_helpers import advance_to, alerts, audit, on


def subscribe_with_consent(c: TestClient, auto_send: bool) -> dict[str, Any]:
    """The shop path, plus the companion's "If I don't answer, send the cancellation email for me" box."""
    pre = c.post("/api/review/preflight", json={"merchant_url": "/shop/penwright", "plan_key": "penwright-pro"}).json()
    res = c.post(f"/api/reviews/{pre['review_id']}/consent", json={"user_id": "priya", "auto_send_notice": auto_send})
    assert res.status_code == 200 and res.json()["auto_send_notice"] is auto_send
    created = c.post("/api/checkout/create", json={"merchant_id": "penwright", "plan_key": "penwright-pro"}).json()
    c.post("/api/checkout/mock-approve", json={"paypal_id": created["paypal_id"]})
    sub = c.post("/api/subscriptions/register", json={"paypal_id": created["paypal_id"], "merchant_id": "penwright",
                                                      "plan_key": "penwright-pro", "review_id": pre["review_id"]})
    assert sub.status_code == 200
    # once linked, the choice can't be changed through the review any more
    again = c.post(f"/api/reviews/{pre['review_id']}/consent", json={"auto_send_notice": not auto_send})
    assert again.status_code == 409
    return sub.json()


def notice_of(c: TestClient, sub_id: str) -> dict[str, Any]:
    return next(n for n in c.get("/api/notices?user=priya").json() if n["subscription_id"] == sub_id)


def test_opt_in_sends_the_email_when_the_timer_cancels(demo_client: TestClient) -> None:
    c = demo_client
    sub = subscribe_with_consent(c, auto_send=True)
    assert sub["consent_snapshot"]["auto_send_notice"] is True
    assert audit(c, "consent_snapshot", subscription_id=sub["id"])[0]["details"]["auto_send_notice"] is True
    advance_to(c, 6)  # no answer on Day 5 -> the timer cancels on Day 6 (R2)
    n = notice_of(c, sub["id"])
    assert n["status"] == "sent" and n["sent_via"] == "auto_on_timer" and n["edited"] is False
    (sent,) = audit(c, "notice_auto_sent", subscription_id=sub["id"])
    assert sent["rule_id"] == "R2" and sent["actor"] == "timer" and sent["decision"] == "allowed"
    (done,) = alerts(c, kind="cancelled")
    assert "I sent your cancellation email for you, as you asked." in done["body"]
    advance_to(c, 7)
    assert not alerts(c, kind="notice_unsent")  # nothing left to remind her about
    assert len(audit(c, "paypal_cancel", subscription_id=sub["id"])) == 1  # still the only PayPal write


def test_no_opt_in_means_a_day7_reminder_and_nothing_sent(demo_client: TestClient) -> None:
    c = demo_client
    sub = subscribe_with_consent(c, auto_send=False)
    assert sub["consent_snapshot"]["auto_send_notice"] is False
    advance_to(c, 6)
    n = notice_of(c, sub["id"])
    assert n["status"] == "draft" and not audit(c, "notice_auto_sent")
    (done,) = alerts(c, kind="cancelled")
    assert "ready to review and send" in done["body"]
    advance_to(c, 7)  # the act-by day
    (rem,) = alerts(c, kind="notice_unsent")
    assert rem["body"] == f"Your cancellation email isn't sent yet. The terms need it by {on(8)}."
    assert [(a["action"], a["label"], a.get("notice_id")) for a in rem["actions"]] == [
        ("review_email", "Review email", n["id"])]
    assert notice_of(c, sub["id"])["status"] == "draft"  # never sent without her click
    advance_to(c, 8)
    assert len(alerts(c, kind="notice_unsent")) == 1  # once only


def test_sent_email_gets_no_reminder(demo_client: TestClient) -> None:
    c = demo_client
    sub = subscribe_with_consent(c, auto_send=False)
    advance_to(c, 6)
    n = notice_of(c, sub["id"])
    c.post(f"/api/notices/{n['id']}/send", json={"user_id": "priya", "to": n["to"], "subject": n["subject"],
                                                  "body": n["body"]})
    advance_to(c, 7)
    assert not alerts(c, kind="notice_unsent")

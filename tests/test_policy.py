"""Safety rules R1-R7 (spec 3) and the timer corner cases (4, 5, 10, 12, 29-32, 34). Mock mode."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import timers as tm
from app.core.actions import cancel_confirmed
from app.core.policy import MAX_WRITES_PER_MINUTE, Decision, Policy
from app.core.services import Services
from app.models import Subscription, Timer, User
from app.store import JsonStore
from tests.story_helpers import add_user, advance_to, alerts, audit, sub, subscribe


def svc_of(c: TestClient) -> Services:
    return c.app.state.services  # type: ignore[attr-defined,no-any-return]


def propose(c: TestClient, ids: list[str], user: str = "priya") -> dict:
    return c.post("/api/agent/propose", json={"user_id": user, "subscription_ids": ids}).json()


def confirm(c: TestClient, ids: list[str], token: str | None, user: str = "priya") -> tuple[int, dict]:
    res = c.post("/api/agent/confirm", json={"user_id": user, "token": token, "subscription_ids": ids})
    return res.status_code, res.json()


# ---- R1 consent ------------------------------------------------------------------------------
def test_r1_cancel_needs_a_confirmation_tap(demo_client: TestClient) -> None:
    c = demo_client
    fw = subscribe(c)
    status, body = confirm(c, [fw["id"]], None)
    assert status == 403 and body["rule_id"] == "R1"
    # corner case 29: the agent tries to cancel directly -> blocked, explained, audited
    out = asyncio.run(cancel_confirmed(svc_of(c), "priya", [fw["id"]], None, requested_by="agent"))
    assert isinstance(out, Decision) and out.rule_id == "R1"
    blocked = audit(c, "policy_decision", rule_id="R1", decision="blocked")
    assert any(r["details"]["requested_by"] == "agent" for r in blocked)
    assert sub(c, fw["id"])["status"] == "ACTIVE"
    card = propose(c, [fw["id"]])
    status, body = confirm(c, [fw["id"]], card["token"])
    assert status == 200 and body["all_ok"]


# ---- R2 safety timer ---------------------------------------------------------------------------
def _timer(**kw: object) -> Timer:
    base: dict[str, object] = dict(id="t", subscription_id="s", kind="trial", fire_day=6, status="PENDING",
                                   shown_to_user=True, warning_delivered=True, warned_day=5, billing_day=15)
    return Timer(**{**base, **kw})  # type: ignore[arg-type]


def _sub(**kw: object) -> Subscription:
    base: dict[str, object] = dict(id="s", paypal_id="I-1", plan_key="p", plan_id="P", merchant_id="m",
                                   owner_id="priya", status="ACTIVE", next_billing_day=15)
    return Subscription(**{**base, **kw})  # type: ignore[arg-type]


PRIYA = User(id="priya", name="Priya")


@pytest.mark.parametrize(("timer", "sub_kw", "day", "rule", "ok"), [
    (_timer(), {}, 6, "R2", True),
    (_timer(shown_to_user=False), {}, 6, "R2", False),
    (_timer(warning_delivered=False, warned_day=None), {}, 6, "R2", False),
    (_timer(warned_day=6), {}, 6, "R2", False),  # warned less than 24 sim-hours before
    (_timer(status="KEPT"), {}, 6, "R2", False),
    (_timer(), {}, 15, "R2", False),  # billing date reached
    (_timer(kind="price_rise"), {}, 6, "R2", False),  # auto_cancel_price_rises off
    (_timer(), {"essential": True}, 6, "R6", False),
    (_timer(), {"owner_id": "intruder"}, 6, "R5", False),
])
def test_r2_timer_conditions(timer: Timer, sub_kw: dict, day: int, rule: str, ok: bool, store: JsonStore) -> None:
    d = Policy().check_timer_fire(store, timer, _sub(**sub_kw), PRIYA, day)
    assert (d.rule_id, d.allowed) == (rule, ok)
    assert store.audit.entries()[-1].event == "policy_decision"


def test_r2_price_rise_allowed_with_setting(store: JsonStore) -> None:
    user = PRIYA.model_copy(update={"settings": PRIYA.settings.model_copy(update={"auto_cancel_price_rises": True})})
    assert Policy().check_timer_fire(store, _timer(kind="price_rise"), _sub(), user, 6).allowed


# ---- R3 tokens ---------------------------------------------------------------------------------
def test_r3_expired_reused_mismatched_and_foreign_tokens(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    fw = subscribe(c, review=False)  # a second Penwright subscription
    intruder = add_user(c)
    store = svc_of(c).store
    # mismatched list
    tok = propose(c, [fw["id"]])["token"]
    assert confirm(c, [fw["id"], main["id"]], tok)[1]["rule_id"] == "R3"
    # expired
    tok = propose(c, [fw["id"]])["token"]
    with store.edit("tokens") as tokens:
        t = next(x for x in tokens.items if x.token == tok)
        t.expires_at = t.issued_at - timedelta(seconds=1)
    status, body = confirm(c, [fw["id"]], tok)
    assert status == 403 and "expired" in body["reason"]
    # another user's token
    tok = propose(c, [fw["id"]])["token"]
    assert confirm(c, [fw["id"]], tok, user=intruder)[1]["rule_id"] == "R5"  # ownership checked first
    # reused
    assert confirm(c, [fw["id"]], tok)[0] == 200
    status, body = confirm(c, [fw["id"]], tok)
    assert status == 403 and "already used" in body["reason"]
    assert len(audit(c, "confirm_token_rejected", rule_id="R3")) == 3
    assert all(r["details"].get("token") in (None, "***") for r in audit(c, "confirm_token_issued"))  # masked


# ---- R4 limits ---------------------------------------------------------------------------------
def test_r4_max_ten_per_command(demo_client: TestClient) -> None:
    ids = [f"s{i}" for i in range(11)]
    res = demo_client.post("/api/agent/propose", json={"user_id": "priya", "subscription_ids": ids})
    assert res.status_code == 403 and res.json()["rule_id"] == "R4"


def test_r4_rate_limit_per_user(store: JsonStore) -> None:
    now = [1000.0]
    policy = Policy(clock=lambda: now[0])
    for _ in range(MAX_WRITES_PER_MINUTE):
        assert policy.take_write(store, "priya", "s", "user") is None
    blocked = policy.take_write(store, "priya", "s", "user")
    assert blocked is not None and blocked.rule_id == "R4"
    assert policy.take_write(store, "intruder", "s", "user") is None  # per user
    now[0] += 60
    assert policy.take_write(store, "priya", "s", "user") is None


# ---- R5 ownership ------------------------------------------------------------------------------
def test_r5_another_user_cannot_touch_priyas_subscriptions(demo_client: TestClient) -> None:
    c = demo_client
    pw = subscribe(c)
    intruder = add_user(c)
    res = c.post("/api/agent/propose", json={"user_id": intruder, "subscription_ids": [pw["id"]]})
    assert res.status_code == 403 and res.json()["rule_id"] == "R5"
    assert c.post(f"/api/subscriptions/{pw['id']}/keep", json={"user_id": intruder}).json()["status"] == "blocked"
    res = c.post(f"/api/subscriptions/{pw['id']}/essential", json={"user_id": intruder, "essential": True})
    assert res.status_code == 403
    advance_to(c, 5)
    alert = alerts(c, kind="reminder")[0]
    assert c.post(f"/api/alerts/{alert['id']}/act", json={"user_id": intruder, "action": "cancel"}).status_code == 403
    assert sub(c, pw["id"])["status"] == "ACTIVE" and sub(c, pw["id"])["kept_day"] is None


# ---- R6 essential ------------------------------------------------------------------------------
def test_r6_essential_never_auto_cancelled_but_manual_ok(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    c.post(f"/api/subscriptions/{main['id']}/essential", json={"user_id": "priya", "essential": True})
    advance_to(c, 6)
    assert sub(c, main["id"])["status"] == "ACTIVE"
    assert audit(c, "policy_decision", rule_id="R6", decision="blocked", subscription_id=main["id"])
    status, body = confirm(c, [main["id"]], propose(c, [main["id"]])["token"])
    assert status == 200 and body["all_ok"]


# ---- R7 / corner case 34: per-item results, nothing claimed that PayPal didn't confirm ---------------
def test_r7_partial_failure_reports_per_item(demo_client: TestClient) -> None:
    c = demo_client
    main, second = subscribe(c), subscribe(c, review=False)
    svc_of(c).gw.mock.inject_failure("cancel", status=500, times=4)  # type: ignore[union-attr]
    ids = sorted([main["id"], second["id"]])
    status, body = confirm(c, ids, propose(c, ids)["token"])
    assert status == 200 and not body["all_ok"]
    outcomes = {r["subscription_id"]: r["outcome"] for r in body["results"]}
    assert sorted(outcomes.values()) == ["cancelled", "failed"]
    failed = next(k for k, v in outcomes.items() if v == "failed")
    assert sub(c, failed)["status"] == "ACTIVE"


# ---- corner cases on the timer path -----------------------------------------------------------
def test_keep_vs_timer_race_is_consistent(demo_client: TestClient) -> None:
    """Corner case 10: Keep and the Day 6 timer at the same time; whoever writes first wins."""
    c = demo_client
    main = subscribe(c)
    advance_to(c, 5)
    svc = svc_of(c)
    from app.clock import advance

    async def race() -> tm.KeepResult:
        _, kept = await asyncio.gather(advance(svc, 1), tm.keep(svc, "priya", main["id"]))
        return kept

    kept = c.portal.call(race)  # type: ignore[attr-defined]
    timer = next(t for t in c.get("/api/timers?user=priya").json() if t["subscription_id"] == main["id"])
    status = sub(c, main["id"])["status"]
    assert (kept.status, timer["status"], status) in {("kept", "KEPT", "ACTIVE"), ("too_late", "FIRED", "CANCELLED")}


def test_failed_warnings_block_auto_cancel(demo_client: TestClient) -> None:
    """Corner case 12: warning delivery failed -> no auto-cancel; at the billing date an urgent alert only."""
    c = demo_client
    main = subscribe(c)
    svc_of(c).notifier.fail_in_app = True
    advance_to(c, 15)
    assert sub(c, main["id"])["status"] == "ACTIVE"
    assert audit(c, "timer_warning_failed")
    assert audit(c, "policy_decision", rule_id="R2", decision="blocked", subscription_id=main["id"])
    timer = next(t for t in c.get("/api/timers?user=priya").json() if t["subscription_id"] == main["id"])
    assert timer["status"] == "FAILED" and alerts(c, kind="urgent")


def test_cancel_failure_switches_to_layer2(demo_client: TestClient) -> None:
    """Corner case 4: PayPal cancel fails -> timer FAILED, written notice + ACTION NEEDED link, no "Done"."""
    c = demo_client
    main = subscribe(c)
    advance_to(c, 5)
    svc_of(c).gw.mock.inject_failure("cancel", status=503, times=4)  # type: ignore[union-attr]
    advance_to(c, 6)
    assert sub(c, main["id"])["status"] == "ACTIVE" and not alerts(c, kind="cancelled")
    action_needed = alerts(c, kind="action_needed")
    assert action_needed and action_needed[0]["actions"][0]["action"] == "open_autopay"
    assert c.get("/api/notices?user=priya").json()


def test_layer2_merchant_flow(demo_client: TestClient) -> None:
    c = demo_client
    c.post("/api/demo/toggle-fair-trial/penwright")
    main = subscribe(c)
    timer = next(t for t in c.get("/api/timers?user=priya").json() if t["subscription_id"] == main["id"])
    assert timer["layer2"] and timer["fire_day"] == 5 and timer["reminder_day"] == 4
    advance_to(c, 5)
    assert sub(c, main["id"])["status"] == "ACTIVE"  # SubGuard can't cancel for non-members
    alert = alerts(c, kind="action_needed")[0]
    assert alert["level"] == "action_needed" and alert["actions"][0]["url"].startswith("https://www.sandbox.paypal.com")
    assert c.get("/api/notices?user=priya").json()[0]["subscription_id"] == main["id"]
    advance_to(c, 14)
    assert alerts(c, kind="urgent")  # still ACTIVE 24 sim-hours before the charge


def test_paypal_side_suspend_cancels_timer(demo_client: TestClient) -> None:
    """Corner case 5: the merchant suspends on PayPal's side -> show it, no action, pending timer cancelled."""
    c = demo_client
    main = subscribe(c)
    c.portal.call(svc_of(c).gw.mock.set_status, main["paypal_id"], "SUSPENDED")  # type: ignore[attr-defined,union-attr]
    advance_to(c, 1)
    assert sub(c, main["id"])["status"] == "SUSPENDED"
    timer = next(t for t in c.get("/api/timers?user=priya").json() if t["subscription_id"] == main["id"])
    assert timer["status"] == "CANCELLED" and audit(c, "status_sync", subscription_id=main["id"])


def test_short_trial_needs_a_manual_decision(demo_client: TestClient) -> None:
    """Corner case 13: subscribing late in the trial window -> no auto timer, decide-now alert."""
    c = demo_client
    svc = svc_of(c)

    async def late_signup() -> None:
        sub_ = Subscription(id="s-late", paypal_id="I-LATE", plan_key="penwright-pro", plan_id="P",
                            merchant_id="penwright", owner_id="priya", signup_day=0, next_billing_day=2)
        await tm.create_trial_timer(svc, sub_)

    c.portal.call(late_signup)  # type: ignore[attr-defined]
    assert alerts(c, kind="decide_now") and audit(c, "timer_not_created", rule_id="R2")

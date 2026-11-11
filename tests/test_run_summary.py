"""Live demo "What SubGuard did" (D-121): this run only, plain rows, every policy decision, no low-level noise."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.story_helpers import advance_to, alerts, audit, cancel_via_alert, on, subscribe

NOISE = ("paypal_call", "clock_advanced", "demo_control", "paypal_subscription_verified", "confirm_token_issued")


def summary(c: TestClient, user: str = "priya") -> dict[str, Any]:
    res = c.get(f"/api/audit-log/summary?user={user}")
    assert res.status_code == 200, res.text
    return res.json()


def test_empty_before_any_subscription(demo_client: TestClient) -> None:
    s = summary(demo_client)
    assert s["subscription_id"] is None and s["rows"] == [] and s["full_log_entries"] >= 0


def test_cancel_run_reads_as_a_short_story(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    advance_to(c, 11)
    s = summary(c)
    rows = s["rows"]
    assert s["subscription_id"] == main["id"] and s["paypal_id"] == main["paypal_id"]
    texts = " | ".join(r["text"] for r in rows)
    for want in ("Read the fine print", "approved the trial in PayPal", "Set a safety timer", "Asked you",
                 "Allowed the cancel", "Cancelled your subscription (ACTIVE → CANCELLED)",
                 "Checked PayPal: no active subscription"):
        assert want in texts, want
    assert len(rows) < len(audit(c)) / 2  # far shorter than the full log
    seqs = {r["seq"] for r in rows}
    assert not [e for e in audit(c) if e["seq"] in seqs and e["event"] in NOISE]
    policy = next(r for r in rows if r["who"] == "Policy")
    assert policy["rule_id"] == "R1" and policy["decision"] == "allowed"
    cancel = next(r for r in rows if "Cancelled your subscription" in r["text"])
    entry = audit(c, "paypal_cancel")[-1]
    assert cancel["proof"] == entry["paypal_debug_id"] and cancel["rule_id"] == "R1"
    assert all(r["who"] != "You" for r in rows) and any(r["who"] == "Priya" for r in rows)
    assert [r["seq"] for r in rows] == sorted(seqs)


def test_only_the_latest_run(demo_client: TestClient) -> None:
    c = demo_client
    first = subscribe(c)
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    second = subscribe(c)
    s = summary(c)
    assert s["subscription_id"] == second["id"] != first["id"]
    old = {e["seq"] for e in audit(c) if e.get("subscription_id") == first["id"]}
    assert not [r for r in s["rows"] if r["seq"] in old]
    assert sum("Read the fine print" in r["text"] for r in s["rows"]) == 1  # this run's review only


def test_blocked_decisions_are_always_shown(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    res = c.post("/api/agent/confirm", json={"user_id": "priya", "token": "not-a-real-token",
                                             "subscription_ids": [main["id"]]})
    assert res.status_code >= 400 or not res.json().get("ok", True)
    blocked = [r for r in summary(c)["rows"] if r["decision"] == "blocked"]
    assert blocked and blocked[0]["who"] == "Policy" and blocked[0]["kind"] == "warn"
    assert blocked[0]["text"].startswith("Blocked")


def test_live_demo_page_has_summary_and_folded_full_log(client: TestClient) -> None:
    html = client.get("/?demo=1").text
    for t in ("audit-summary", "audit-full-toggle", "audit-log-grid", "audit-log-export", "audit-chain"):
        assert f'data-testid="{t}"' in html, t
    assert 'id="audit-full" class="audit-full" hidden' in html and "/static/audit-summary.js" in html
    pipeline = html.split('id="pipeline"', 1)[1].split("</section>", 1)[0]
    assert 'id="pp-demo"' in pipeline  # PayPal strip lives inside the step-by-step card
    js = client.get("/static/paypal-card.js").text
    assert '"strip"' in js and "paypal-earlier" in js and "earlier run" in js


# ---- v3 B3 / B4: built from Priya's subscriptions, steps derived from events (no Start demo needed) -------------

def steps(s: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    return {st["key"]: (st["state"], st["detail"]) for st in s["steps"]}


def test_manual_signup_fills_the_summary_and_ticks_steps(demo_client: TestClient) -> None:
    c = demo_client
    assert all(state == "pending" for state, _ in steps(summary(c)).values())
    subscribe(c)  # the shop path, no Start demo
    s = summary(c)
    assert s["rows"], "B3: the summary must not be empty after a manual sign-up"
    st = steps(s)
    assert st["read"] == ("done", f"Risk {s['rows'][0]['text'].split('risk ')[1].split('/')[0]} · act by {on(7)}")
    assert st["approve"][0] == "done" and st["timer"] == ("done", f"Ask {on(5)} · cancel {on(6)}")
    assert st["ask"][0] == st["outcome"][0] == st["proof"][0] == "pending"
    advance_to(c, 5)
    st = steps(summary(c))
    assert st["wait"] == ("done", "5 days") and st["ask"] == ("done", f"Asked {on(5)}")
    assert st["outcome"] == ("active", "waiting for Priya")
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    assert steps(summary(c))["outcome"] == ("done", f"Cancelled {on(5)}")
    advance_to(c, 11)
    assert steps(summary(c))["proof"] == ("done", "Checked PayPal: no charge")


def test_steps_for_no_answer_and_keep(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 6)
    assert steps(summary(c))["outcome"] == ("done", f"Auto-cancelled {on(6)} (R2)")
    c.post("/api/demo/reset")
    main = subscribe(c)
    advance_to(c, 5)
    c.post(f"/api/subscriptions/{main['id']}/keep", json={"user_id": "priya"})
    advance_to(c, 11)
    st = steps(summary(c))
    assert st["outcome"] == ("done", "Kept") and st["proof"] == ("warn", f"{on(11)}: charged")

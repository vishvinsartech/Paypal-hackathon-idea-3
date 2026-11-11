"""Key dates (D-115): real sign-up time, every "Day N" as a calendar date. Phase 3 (U7) took the folded "Key dates"
box off the card (the five dots replace it); `key_dates()` still dates the history rows, so it is tested directly."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.core.sub_dates import date_of_day, key_dates
from app.routes.views import current_timer, sub_view
from tests.story_helpers import advance_to, alerts, cancel_via_alert, subscribe

ORDER = ["subscribed", "check_in", "auto_cancel", "deadline", "trial_end", "first_charge", "step_up"]


def table(c: TestClient, sub_id: str) -> list[dict[str, Any]]:
    svc = c.app.state.services  # type: ignore[attr-defined]
    sub = svc.sub(sub_id)
    timers = svc.store.load("timers").items
    view = sub_view(svc, sub, timers)
    return key_dates(svc, sub, view, current_timer(timers, sub.id), 7)


def rows(c: TestClient, sub_id: str) -> dict[str, str]:
    """key -> "note · Day N · iso" (one string per row, easy to assert on)."""
    return {r["key"]: f"{r['label']} · {r['note']} · Day {r['day']} · {(r['when'] or {}).get('iso', '')}"
            for r in table(c, sub_id)}


def state(c: TestClient, sub_id: str, key: str) -> str:
    return next(r["state"] for r in table(c, sub_id) if r["key"] == key)


def test_dates_follow_the_signup_moment(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    sub = c.app.state.services.sub(main["id"])  # type: ignore[attr-defined]
    at = sub.registered_at
    assert at is not None
    got = rows(c, main["id"])
    assert list(got) == ORDER
    assert got["subscribed"].endswith(at.isoformat())
    for key, day in (("check_in", 5), ("auto_cancel", 6), ("deadline", 7), ("trial_end", 10), ("first_charge", 11)):
        assert got[key].endswith((at + timedelta(days=day)).isoformat()), key
        assert f"· Day {day} ·" in got[key], key
        assert date_of_day(sub, day) == at + timedelta(days=day)
    assert "7 days left" in got["deadline"] and "$24.99" in got["first_charge"] and "$49.99" in got["step_up"]
    assert "Cancels in PayPal unless you tap Keep" in got["auto_cancel"]
    assert state(c, main["id"], "subscribed") == "done" and state(c, main["id"], "deadline") == "upcoming"


def test_after_cancel_on_day5(demo_client: TestClient) -> None:
    c = demo_client
    sid = subscribe(c)["id"]
    advance_to(c, 5)
    assert state(c, sid, "check_in") == "today"
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    got = rows(c, sid)
    assert list(got)[-1] == "first_charge" and "step_up" not in got
    assert "Cancelled in time ✓" in got["deadline"] and state(c, sid, "deadline") == "done"
    assert "Not needed: you cancelled" in got["auto_cancel"] and state(c, sid, "auto_cancel") == "off"
    assert "by you" in got["cancelled"]
    assert "Blocked: no active PayPal subscription" in got["first_charge"]
    assert state(c, sid, "first_charge") == "blocked"


def test_timer_fired_and_kept(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 6)
    got = rows(c, main["id"])
    assert "Cancelled by your safety timer" in got["auto_cancel"] and "by your safety timer" in got["cancelled"]
    c.post("/api/demo/reset")
    main = subscribe(c)
    advance_to(c, 5)
    c.post(f"/api/subscriptions/{main['id']}/keep", json={"user_id": "priya"})
    got = rows(c, main["id"])
    assert "Off: you kept it" in got["auto_cancel"] and "You kept it" in got["deadline"] and "kept" in got
    assert "$24.99" in got["first_charge"]


def test_paypal_card_has_paypal_start_time(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    got = c.get(f"/api/subscriptions/{main['id']}/paypal?user=priya").json()
    signed_up = c.app.state.services.sub(main["id"]).registered_at  # type: ignore[attr-defined]
    assert got["start_time"] and got["start_time"][:10] == signed_up.date().isoformat()
    assert "paypal-start-time" in c.get("/static/paypal-card.js").text

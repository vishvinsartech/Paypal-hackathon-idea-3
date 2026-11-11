"""Key dates on Priya's subscription card (D-115): real sign-up time, every "Day N" as a calendar date."""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.sub_dates import date_of_day
from tests.story_helpers import advance_to, alerts, cancel_via_alert, subscribe

ORDER = ["subscribed", "check_in", "auto_cancel", "deadline", "trial_end", "first_charge", "step_up"]


def rows(html: str) -> dict[str, str]:
    """data-testid="date-<key>" -> that row's HTML."""
    return dict(re.findall(r'<li class="kd [^"]*" data-testid="date-(\w+)">(.*?)</li>', html, re.S))


def state(html: str, key: str) -> str:
    m = re.search(rf'<li class="kd kd-(\w+)" data-testid="date-{key}">', html)
    assert m, key
    return m.group(1)


def iso(html: str) -> str:
    m = re.search(r'<time datetime="([^"]+)"', html)
    assert m, html
    return m.group(1)


def test_dates_follow_the_signup_moment(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    sub = c.app.state.services.sub(main["id"])  # type: ignore[attr-defined]
    at = sub.registered_at
    assert at is not None
    html = c.get("/user").text
    got = rows(html)
    assert list(got) == ORDER
    assert f'data-testid="subscribed-at">Subscribed <time datetime="{at.isoformat()}" data-local="datetime">' in html
    assert at.strftime("%a %d %b %Y, %H:%M UTC") in got["subscribed"]  # UTC fallback; the browser localizes it
    for key, day in (("check_in", 5), ("auto_cancel", 6), ("deadline", 7), ("trial_end", 10), ("first_charge", 11)):
        assert iso(got[key]) == (at + timedelta(days=day)).isoformat(), key
        assert f"· Day {day}</span>" in got[key], key
        assert date_of_day(sub, day) == at + timedelta(days=day)
    assert "7 days left" in got["deadline"] and "$24.99" in got["first_charge"] and "$49.99" in got["step_up"]
    assert "Cancels in PayPal unless you tap Keep" in got["auto_cancel"]
    assert state(html, "subscribed") == "done" and state(html, "deadline") == "upcoming"


def test_after_cancel_on_day5(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    assert state(c.get("/user").text, "check_in") == "today"
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    html = c.get("/user").text
    got = rows(html)
    assert list(got)[-1] == "first_charge" and "step_up" not in got
    assert "Cancelled in time ✓" in got["deadline"] and state(html, "deadline") == "done"
    assert "Not needed: you cancelled" in got["auto_cancel"] and state(html, "auto_cancel") == "off"
    assert "by you" in got["cancelled"] and 'data-local="datetime"' in got["cancelled"]
    assert "Blocked: no active PayPal subscription" in got["first_charge"] and state(html, "first_charge") == "blocked"


def test_timer_fired_and_kept(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 6)
    got = rows(c.get("/user").text)
    assert "Cancelled by your safety timer" in got["auto_cancel"] and "by your safety timer" in got["cancelled"]
    c.post("/api/demo/reset")
    main = subscribe(c)
    advance_to(c, 5)
    c.post(f"/api/subscriptions/{main['id']}/keep", json={"user_id": "priya"})
    html = c.get("/user").text
    got = rows(html)
    assert "Off: you kept it" in got["auto_cancel"] and "You kept it" in got["deadline"] and "kept" in got
    assert "$24.99" in got["first_charge"]


def test_paypal_card_has_paypal_start_time(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    got = c.get(f"/api/subscriptions/{main['id']}/paypal?user=priya").json()
    signed_up = c.app.state.services.sub(main["id"]).registered_at  # type: ignore[attr-defined]
    assert got["start_time"] and got["start_time"][:10] == signed_up.date().isoformat()
    assert "paypal-start-time" in c.get("/static/paypal-card.js").text

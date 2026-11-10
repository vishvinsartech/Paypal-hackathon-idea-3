"""Top-bar tabs (Live demo / Priya's dashboard / Shop / Health / API docs) and Priya's dashboard at /user."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.story_helpers import add_user, advance_to, alerts, cancel_via_alert, subscribe

TABS = ("tab-demo", "tab-user", "view-shop", "tab-health", "tab-docs")


def test_tabs_on_every_page(client: TestClient) -> None:
    for url, active in (("/", "tab-demo"), ("/user", "tab-user")):
        html = client.get(url).text
        for t in TABS:
            assert f'data-testid="{t}"' in html, (url, t)
        tab = re.search(rf'<a class="tab is-active"[^>]*data-testid="{active}"', html, re.S)
        assert tab and 'aria-current="page"' in tab.group(0), url
    html = client.get("/").text
    for href in ("/shop", "/healthz", "/docs"):  # open in a new tab, so the live demo window stays put
        assert re.search(rf'href="{href}"[^>]*target="_blank"', html), href
    assert ">Priya's dashboard<" in html
    assert client.get("/healthz").status_code == 200 and client.get("/docs").status_code == 200


def test_user_page_empty_state(client: TestClient) -> None:
    html = client.get("/user").text
    assert 'data-testid="user-dashboard"' in html and "Priya's dashboard" in html
    assert "No subscriptions yet" in html and "$0/yr" in html


def test_user_page_tells_her_story(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    (check,) = alerts(c, kind="reminder")
    cancel_via_alert(c, check)
    advance_to(c, 11)
    html = c.get("/user").text
    assert "$524.88/yr" in html and "CANCELLED" in html and "Cancelled Day 5 by Priya" in html
    feed = re.findall(r'<span class="who who-\w+">([^<]+)</span>\s*<span class="txt">([^<]+)', html)
    texts = [f"{who}: {txt.strip()}" for who, txt in feed]
    order = ["SubGuard: Read the fine print before PayPal", "Priya: Approved the trial in PayPal",
             "SubGuard: Set a safety timer and showed it to her: check in on Day 5, cancel on Day 6",
             "SubGuard: Asked her", "Priya: Tapped Cancel.", "PayPal: Cancelled the subscription in PayPal",
             "SubGuard: Drafted the cancellation email", "PayPal: First charge due: blocked."]
    pos = [next(i for i, t in enumerate(texts) if t.startswith(o)) for o in order]
    assert pos == sorted(pos), texts
    assert "Draft, not sent yet" in html and "Day 2: opened 1×" in html


def test_user_page_shows_only_her_data(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    add_user(c)
    html = c.get("/user?user=intruder").text
    assert "Intruder's dashboard" in html and "No subscriptions yet" in html and "Penwright Studio" not in html

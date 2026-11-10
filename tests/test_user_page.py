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
    toggle = re.search(r'<button[^>]*data-testid="theme-toggle"[^>]*>', html)
    assert toggle and 'aria-label="Switch to light theme"' in toggle.group(0)
    assert 'h.dataset.theme = t' in html.split("</head>")[0]  # theme set before first paint
    assert re.search(r'src="https://cdn\.jsdelivr\.net/npm/ag-charts-community@\d+\.\d+\.\d+/', html)  # pinned
    assert client.get("/healthz").status_code == 200 and client.get("/docs").status_code == 200


def test_user_page_empty_state(client: TestClient) -> None:
    html = client.get("/user").text
    assert 'data-testid="user-dashboard"' in html and "Hi Priya, here's your SubGuard." in html
    assert "$0/yr" in html and "Your story starts when you click PayPal" in html
    for t in ("subs-grid", "chart-cost", "chart-usage", "chart-risk"):
        assert f'data-testid="{t}"' in html, t


def test_user_page_tells_her_story(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    (check,) = alerts(c, kind="reminder")
    cancel_via_alert(c, check)
    n = c.get("/api/notices?user=priya").json()[0]
    c.post(f"/api/notices/{n['id']}/send", json={"user_id": "priya", "to": n["to"], "subject": n["subject"],
                                                  "body": n["body"]})
    advance_to(c, 11)
    html = c.get("/user").text
    assert "$524.88/yr" in html
    feed = re.findall(r'<span class="who who-\w+">([^<]+)</span>\s*<span class="txt">([^<]+)', html)
    texts = [f"{who}: {txt.strip()}" for who, txt in feed]
    order = ["SubGuard: Read the fine print for you before PayPal", "You: You approved the trial in PayPal",
             "SubGuard: Set a safety timer and told you about it: check in on Day 5, cancel on Day 6",
             "SubGuard: Asked you", "You: You tapped Cancel.", "PayPal: Cancelled your subscription",
             "SubGuard: Drafted the cancellation email", "You: You sent the cancellation email",
             "PayPal: First charge due: blocked."]
    pos = [next(i for i, t in enumerate(texts) if t.startswith(o)) for o in order]
    assert pos == sorted(pos), texts
    assert "Email sent (demo)" in html and ">Your decisions<" in html


def test_user_page_shows_only_her_data(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    add_user(c)
    html = c.get("/user?user=intruder").text
    assert "Hi Intruder, here's your SubGuard." in html and "Penwright Studio" not in html
    a = c.get("/api/analytics?user=intruder").json()
    assert a["activity"]["total"] == 0 and a["usage"]["total"] == 0 and a["cost"]["preview"]


def test_analytics_numbers_come_from_code(demo_client: TestClient) -> None:
    """D-108: the chart data. Money from the PayPal plan (Decimal strings), risk from the review, the rest from logs."""
    c = demo_client
    before = c.get("/api/analytics").json()
    assert before["cost"]["preview"] and before["cost"]["rows"][-1]["if_kept"] == "524.88"
    assert before["risk"] is None and before["activity"]["total"] == 0
    subscribe(c)
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    a = c.get("/api/analytics").json()
    cost = a["cost"]
    assert not cost["preview"] and cost["symbol"] == "$" and len(cost["rows"]) == 12
    assert [r["charge"] for r in cost["rows"][:4]] == ["24.99", "24.99", "24.99", "49.99"]
    assert cost["rows"][-1] == {"month": "M12", "charge": "49.99", "if_kept": "524.88", "you_pay": "0"}
    assert cost["protected_text"] == "$524.88"
    risk = a["risk"]
    assert risk["score"] == 87 and sum(p["points"] for p in risk["parts"]) == 86.5  # 86.5 rounds half-up to 87
    assert risk["parts"][0]["label"] == "Notice Period"
    assert {r["actor"] for r in a["activity"]["by_actor"]} >= {"user", "policy", "system"}
    assert sum(r["count"] for r in a["activity"]["by_actor"]) == a["activity"]["total"]
    u = a["usage"]
    assert (u["total"], u["deadline_day"], u["first_charge_day"]) == (2, 7, 11)
    assert [r["opens"] for r in u["rows"][:5]] == [0, 0, 1, 0, 1]

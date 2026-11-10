"""Top bar + footer on both pages, and Priya's dashboard at /user (the product view; D-110, D-112)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.story_helpers import add_user, advance_to, alerts, cancel_via_alert, subscribe

TABS = ("tab-demo", "tab-user", "view-shop")
FOOTER = ("footer", "footer-license", "footer-github", "dev-menu", "dev-health", "dev-docs", "health-dots")


def top_bar(html: str) -> str:
    return html.split('<header class="topbar"', 1)[1].split("</header>", 1)[0]


def test_top_bar_and_footer_on_both_pages(client: TestClient) -> None:
    for url, active in (("/", "tab-demo"), ("/user", "tab-user")):
        html = client.get(url).text
        for t in (*TABS, *FOOTER, "theme-toggle"):
            assert f'data-testid="{t}"' in html, (url, t)
        tab = re.search(rf'<a class="tab is-active"[^>]*data-testid="{active}"', html, re.S)
        assert tab and 'aria-current="page"' in tab.group(0), url
        bar = top_bar(html)
        for gone in ("health-dots", "/healthz", "/docs"):  # moved to the footer's Developer menu
            assert gone not in bar, (url, gone)
        footer = html.split('data-testid="footer"', 1)[1].split("</footer>", 1)[0]
        for text in ("Fictional merchant", "PayPal Sandbox", "MIT license", "GitHub"):
            assert text in footer, text
        assert "https://github.com/vishvinsartech/Paypal-hackathon-idea-3" in footer
    html = client.get("/").text
    for href in ("/shop", "/healthz", "/docs"):  # new tabs, so the live demo window stays put
        assert re.search(rf'href="{href}"[^>]*target="_blank"', html), href
    assert ">Priya's dashboard<" in html
    toggle = re.search(r'<button[^>]*data-testid="theme-toggle"[^>]*>', html)
    assert toggle and 'aria-label="Switch to light theme"' in toggle.group(0)
    assert 'h.dataset.theme = t' in html.split("</head>")[0]  # theme set before first paint
    assert "ag-charts-community" not in html  # charts only on Priya's dashboard
    user = client.get("/user").text
    assert re.search(r'src="https://cdn\.jsdelivr\.net/npm/ag-charts-community@\d+\.\d+\.\d+/', user)  # pinned
    assert client.get("/healthz").status_code == 200 and client.get("/docs").status_code == 200


def test_user_page_empty_state(client: TestClient) -> None:
    html = client.get("/user").text
    assert 'data-testid="user-dashboard"' in html and "Hi Priya, here's your SubGuard." in html
    assert "No subscriptions yet." in html and "Try the Penwright shop." in html and 'data-testid="user-empty"' in html
    for t in ("user-protected", "user-cancelled", "user-activity", "chart-cost", "chart-usage", "chart-risk",
              "chat-open"):
        assert f'data-testid="{t}"' in html, t
    for gone in ("subs-grid", "Your subscriptions</span>", "Your decisions", "sub-card", "user-reminder",
                 "proof-banner"):
        assert gone not in html, gone


def test_card_reminder_and_proof(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    html = c.get("/user").text
    assert 'data-testid="sub-card"' in html and 'data-testid="status-penwright">ACTIVE<' in html
    assert re.search(r'data-testid="risk-score">Risk 8\d/100<', html)
    assert "Site says: trial ends Day 10 · <strong>Real last day to cancel: Day 7.</strong>" in html
    assert 'data-testid="next-charge">Day 11 · $24.99<' in html
    assert 'data-sub-keep="' in html and 'data-sub-cancel="' in html
    assert f'href="/subscriptions/{main["id"]}?user=priya" data-testid="view-review">View fine-print review<' in html
    assert "user-reminder" not in html  # no check-in before Day 5

    advance_to(c, 5)
    (check,) = alerts(c, kind="reminder")
    html = c.get("/user").text
    assert 'data-testid="user-reminder"' in html and "Your Penwright trial ends on Day 10" in html
    assert "Opened twice in 5 days (last on Day 4)." in html
    assert "SubGuard suggests: cancel. You decide." in html and ">Advice<" in html
    assert "costs $524.88 in the first paid year" in html
    for action in ("keep", "cancel"):
        assert f'data-alert="{check["id"]}" data-action="{action}"' in html

    cancel_via_alert(c, check)  # reminder Cancel -> confirmation card -> (email preview in the browser)
    html = c.get("/user").text
    assert "user-reminder" not in html and 'data-testid="status-penwright">CANCELLED<' in html
    assert "Cancelled in PayPal on Day 5 by you" in html and "data-sub-cancel" not in html
    assert "Your cancellation email is ready to review and send." in html
    assert "Restart trial" not in html

    advance_to(c, 11)
    html = c.get("/user").text
    banner = re.search(r'data-testid="proof-banner"[^>]*><strong>([^<]+)</strong>', html)
    assert banner and banner.group(1) == "First charge due today: blocked. No active PayPal subscription."
    assert "Day 11 · blocked (no active PayPal subscription)" in html
    assert re.search(r'data-testid="user-protected">.*?\$524\.88/yr', html, re.S)
    assert re.search(r'data-testid="user-cancelled">.*?>1<', html, re.S)
    advance_to(c, 12)
    assert "Day 11: first charge blocked. No active PayPal subscription." in c.get("/user").text


def test_keep_card_means_no_buttons(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 5)
    assert c.post(f"/api/subscriptions/{main['id']}/keep", json={"user_id": "priya"}).json()["status"] == "kept"
    html = c.get("/user").text
    assert "You kept it on Day 5" in html and "data-sub-keep" not in html and "user-reminder" not in html


def test_activity_list_tells_her_story(demo_client: TestClient) -> None:
    """The AG Grid activity list (/api/activity), in the second person, in order."""
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    n = c.get("/api/notices?user=priya").json()[0]
    c.post(f"/api/notices/{n['id']}/send", json={"user_id": "priya", "to": n["to"], "subject": n["subject"],
                                                  "body": n["body"]})
    advance_to(c, 11)
    texts = [f"{r['who']}: {r['text']}" for r in c.get("/api/activity?user=priya").json()]
    order = ["SubGuard: Read the fine print for you before PayPal", "You: You approved the trial in PayPal",
             "SubGuard: Set a safety timer and told you about it: check in on Day 5, cancel on Day 6",
             "SubGuard: Asked you", "You: You tapped Cancel.", "PayPal: Cancelled your subscription",
             "SubGuard: Drafted the cancellation email", "You: You sent the cancellation email",
             "PayPal: First charge due: blocked."]
    pos = [next(i for i, t in enumerate(texts) if t.startswith(o)) for o in order]
    assert pos == sorted(pos), texts
    assert "Email sent (demo)" in c.get("/user").text


def test_user_page_shows_only_her_data(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    add_user(c)
    html = c.get("/user?user=intruder").text
    assert "Hi Intruder, here's your SubGuard." in html and "No subscriptions yet." in html
    assert "Penwright Studio" not in html
    assert c.get("/api/activity?user=intruder").json() == []
    a = c.get("/api/analytics?user=intruder").json()
    assert a["usage"]["total"] == 0 and a["cost"]["preview"]


def test_analytics_numbers_come_from_code(demo_client: TestClient) -> None:
    """D-108: the chart data. Money from the PayPal plan (Decimal strings), risk from the review, usage from logs."""
    c = demo_client
    before = c.get("/api/analytics").json()
    assert before["cost"]["preview"] and before["cost"]["rows"][-1]["if_kept"] == "524.88"
    assert before["risk"] is None and "activity" not in before
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
    u = a["usage"]
    assert (u["total"], u["deadline_day"], u["first_charge_day"]) == (2, 7, 11)
    assert [r["opens"] for r in u["rows"][:5]] == [0, 0, 1, 0, 1]

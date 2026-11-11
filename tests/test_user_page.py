"""Top bar + footer, and Priya's SubGuard at `/` (the product view; FIX_PLAN Phase 3 U1-U12, D-148).
`/user` and `/me` redirect to `/`."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.story_helpers import ACT_BY, add_user, advance_to, alerts, cancel_via_alert, on, subscribe

FOOTER = ("footer", "footer-license", "footer-github", "dev-menu", "dev-health", "dev-docs", "health-dots")


def top_bar(html: str) -> str:
    return html.split('<header class="topbar"', 1)[1].split("</header>", 1)[0]


def card_of(html: str, merchant: str = "penwright") -> str:
    """One subscription card's HTML (the one whose status pill is for `merchant`)."""
    for part in html.split('data-testid="sub-card"')[1:]:
        part = part.split("</article>", 1)[0]
        if f'data-testid="status-{merchant}"' in part:
            return part
    raise AssertionError(f"no card for {merchant}")


def test_top_bar_and_footer(client: TestClient) -> None:
    """U1 / U3: one top bar on every SubGuard page; developer links only in the footer."""
    subscribe(client)
    sub_id = client.get("/api/subscriptions?user=priya").json()[0]["id"]
    for url in ("/", f"/subscriptions/{sub_id}?user=priya"):
        html = client.get(url).text
        bar = top_bar(html)
        for t in ("brand", "mode-badge", "chat-open", "theme-toggle", "user-avatar"):
            assert f'data-testid="{t}"' in bar, (url, t)
        for t in FOOTER:
            assert f'data-testid="{t}"' in html, (url, t)
        for gone in ("health-dots", "/healthz", "/docs", "tab-demo", "tab-user", "view-shop", "/shop"):
            assert gone not in bar, (url, gone)
        footer = html.split('data-testid="footer"', 1)[1].split("</footer>", 1)[0]
        for text in ("Fictional merchant", "PayPal Sandbox", ">MIT<", "GitHub", "Developer"):
            assert text in footer, text
        assert "https://github.com/vishvinsartech/Paypal-hackathon-idea-3" in footer
    html = client.get("/").text
    for href in ("/healthz", "/docs"):  # new tabs, so the demo window stays put
        assert re.search(rf'href="{href}"[^>]*target="_blank"', html), href
    toggle = re.search(r'<button[^>]*data-testid="theme-toggle"[^>]*>', html)
    assert toggle and 'aria-label="Switch to light theme"' in toggle.group(0) and "title=" in toggle.group(0)
    assert "theme-label" not in html  # an icon with a tooltip, no "Dark" text (U1)
    assert 'h.dataset.theme = t' in html.split("</head>")[0]  # theme set before first paint
    assert "ag-charts-community" not in html  # charts live on the evidence page (U25)
    assert client.get("/healthz").status_code == 200 and client.get("/docs").status_code == 200


def test_old_urls_redirect(client: TestClient) -> None:
    for old in ("/user", "/me", "/user?user=priya"):
        r = client.get(old, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"].startswith("/"), old
    assert client.get("/me?user=priya").url.path == "/"


def test_empty_state(client: TestClient) -> None:
    """U11: one friendly card and an "Open the demo shop" button. No zero KPIs."""
    html = client.get("/").text
    assert 'data-testid="user-dashboard"' in html and "Hi Priya, here's your SubGuard." in html
    assert 'data-testid="user-empty"' in html and "No subscriptions yet." in html
    assert "When you start a free trial, SubGuard checks it before you pay" in html
    assert re.search(r'href="/shop\?user=priya"[^>]*data-testid="empty-open-shop">Open the demo shop<', html)
    assert re.search(r'<aside class="side" id="home-side"[^>]*hidden', html)  # KPIs hidden while empty
    for t in ("nav-overview", "nav-activity", "nav-emails", "chat-open"):
        assert f'data-testid="{t}"' in html, t
    for gone in ("subs-grid", "sub-card", "user-reminder", "proof-banner", "chart-cost", "history-grid"):
        assert f'data-testid="{gone}"' not in html, gone


def test_card_reminder_and_proof(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    html = c.get("/").text
    card = card_of(html)
    assert 'data-testid="status-penwright">ACTIVE<' in card
    assert re.search(r'data-testid="risk-score">Risk 8\d/100<', card)
    assert f'data-testid="cost-line">$0 today, then $24.99/month from {on(11)}<' in card  # U7: the big cost line
    assert 'data-testid="cost-sub">Rises to $49.99 after 3 months · up to $524.88 in year one<' in card
    assert f'<strong data-testid="act-by">{ACT_BY}</strong>' in card
    assert f"the site says the trial ends {on(10)}" in card
    assert 'data-testid="trial-timeline"' in card and 'data-testid="t5-act_by"' in card
    assert 'data-sub-keep="' in card and 'data-sub-cancel="' in card and ">Cancel trial<" in card
    assert f'href="/subscriptions/{main["id"]}?user=priya" data-testid="view-review">See evidence<' in card
    assert 'data-testid="paypal-verified"' in card
    assert f'<code data-testid="paypal-sub-id">{main["paypal_id"]}</code>' in card
    for gone in ("key-dates", "kd-details", "pp-user", "Verified with PayPal</h3>"):  # merged into the card (U7)
        assert gone not in html, gone
    assert "user-reminder" not in html  # no check-in before Day 5
    nxt = html.split('data-testid="next-decision"', 1)[1].split("</section>", 1)[0]
    assert f"<strong>{on(5)}</strong> · Keep or cancel" in nxt  # U9

    advance_to(c, 5)
    (check,) = alerts(c, kind="reminder")
    html = c.get("/").text
    card = card_of(html)
    band = card.split('data-testid="user-reminder"', 1)[1]
    assert "Keep it or cancel?" in band and f"Your Penwright trial ends on {on(10)}" in band
    assert (f"Opened twice in 5 days, last on {on(4)} (from Penwright&#39;s app activity, simulated in this demo)."
            in band)
    assert "SubGuard suggests: cancel. You decide." in band and ">Advice<" in band
    assert "costs $524.88 in the first paid year" in band
    assert "App ✓ · Email ✓ · SMS ✓" in band  # U4: no "in_app: shown · email: mocked"
    for action in ("keep", "cancel"):  # U8: the card's buttons ARE the check-in decision, only one pair
        assert f'data-alert="{check["id"]}" data-action="{action}"' in card
    assert "data-sub-keep" not in html and "data-sub-cancel" not in html
    assert html.count('data-action="keep"') == 1 and html.count('data-action="cancel"') == 1

    cancel_via_alert(c, check)  # check-in Cancel -> confirmation card -> (email preview in the browser)
    html = c.get("/").text
    card = card_of(html)
    assert "user-reminder" not in html and 'data-testid="status-penwright">CANCELLED<' in card
    assert f"Cancelled in PayPal on {on(5)} by you" in card and "data-sub-cancel" not in card
    assert f"Cancelled. You won&#39;t be charged $24.99 on {on(11)}." in card
    assert 'data-testid="start-new-trial"' in card and "Penwright may not offer a second free trial." in card  # U12
    assert "Your cancellation email is ready to review and send." in html
    assert "Restart trial" not in html

    advance_to(c, 11)
    html = c.get("/").text
    banner = re.search(r'data-testid="proof-banner"[^>]*><strong>([^<]+)</strong>', html)
    assert banner and banner.group(1) == ("First charge due today. Checked PayPal: no active subscription, "
                                          "so no charge can be taken.")
    assert re.search(r'data-testid="user-avoided">\$24\.99<', html)  # D10: Charges avoided
    assert 'data-testid="user-year-one">up to $524.88 in year one<' in html
    assert 'data-testid="user-cancelled">Cancelled in PayPal: 1<' in html
    advance_to(c, 12)
    later = f"First charge was due {on(11)}. Checked PayPal: no active subscription, so no charge can be taken."
    assert later in c.get("/").text


def test_keep_card_means_no_buttons(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 5)
    assert c.post(f"/api/subscriptions/{main['id']}/keep", json={"user_id": "priya"}).json()["status"] == "kept"
    html = c.get("/").text
    assert f"You kept it on {on(5)}" in html and "data-sub-keep" not in html and "user-reminder" not in html
    assert 'data-testid="deadline-line"' not in html  # nothing to act on any more


def test_activity_list_tells_her_story(demo_client: TestClient) -> None:
    """/api/activity, in the second person, in order, with calendar dates (B2)."""
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
             f"SubGuard: Set a safety timer and told you about it: check in on {on(5)}, cancel on {on(6)}",
             "SubGuard: Asked you", "You: You tapped Cancel.", "PayPal: Cancelled your subscription",
             "SubGuard: Drafted the cancellation email", "You: You sent the cancellation email",
             "SubGuard: Checked PayPal: no active subscription, so no charge can be taken."]
    pos = [next(i for i, t in enumerate(texts) if t.startswith(o)) for o in order]
    assert pos == sorted(pos), texts
    assert not any("mock" in t or "fixtures" in t for t in texts)  # U4
    html = c.get("/").text
    assert "Email sent (demo)" in html
    did = html.split('data-testid="audit-summary"', 1)[1].split("</ol>", 1)[0]
    assert did.count('data-testid="audit-summary-row"') == 5  # U9: the 5 latest meaningful events
    assert did.index("Checked PayPal: no active subscription") < did.index("You sent the cancellation email")


def test_subscription_history_rows(demo_client: TestClient) -> None:
    """D-118: one history row per subscription, with trial / deadline days, outcome and its audit-log events."""
    c = demo_client
    assert c.get("/api/subscription-history?user=priya").json() == []
    main = subscribe(c)
    (row,) = c.get("/api/subscription-history?user=priya").json()
    assert (row["id"], row["merchant"], row["status"]) == (main["id"], "Penwright Studio", "ACTIVE")
    assert (row["trial_end_day"], row["deadline_day"]) == (10, 7) and row["outcome"] == "Watching for you"
    assert row["next_charge"] == f"{on(11)} · $24.99" and 82 <= row["risk"] <= 92
    assert row["subscribed_at"] and row["events"] == len(row["event_log"]) >= 1
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    (row,) = c.get("/api/subscription-history?user=priya").json()
    assert row["status"] == "CANCELLED" and row["outcome"] == f"Cancelled in PayPal on {on(5)} by you"
    assert any("Cancelled your subscription" in e for e in row["event_log"])
    html = c.get("/").text
    hist = html.split('data-testid="user-history"', 1)[1].split("</ul>", 1)[0]
    assert "Penwright Studio" in hist and 'id="history-grid"' not in html  # U10: grid only with > 5 rows
    add_user(c)
    assert c.get("/api/subscription-history?user=intruder").json() == []  # R5


def test_user_page_shows_only_her_data(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    add_user(c)
    html = c.get("/?user=intruder").text
    assert "Hi Intruder, here's your SubGuard." in html and "No subscriptions yet." in html
    assert "Penwright Studio" not in html
    assert c.get("/api/activity?user=intruder").json() == []
    a = c.get("/api/analytics?user=intruder").json()
    assert a["usage"]["total"] == 0 and a["cost"]["preview"]


def test_analytics_numbers_come_from_code(demo_client: TestClient) -> None:
    """D-108: the chart data. Money from the PayPal plan (Decimal strings), risk from the review, usage from logs.
    U25: risk in four plain categories; the charts are scoped to one subscription on its evidence page."""
    c = demo_client
    before = c.get("/api/analytics").json()
    assert before["cost"]["preview"] and before["cost"]["rows"][-1]["if_kept"] == "524.88"
    assert before["risk"] is None and "activity" not in before
    main = subscribe(c)
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    a = c.get(f"/api/analytics?subscription_id={main['id']}").json()
    cost = a["cost"]
    assert not cost["preview"] and cost["symbol"] == "$" and len(cost["rows"]) == 12
    assert [r["charge"] for r in cost["rows"][:4]] == ["24.99", "24.99", "24.99", "49.99"]
    assert cost["rows"][-1] == {"month": "M12", "charge": "49.99", "if_kept": "524.88", "you_pay": "0"}
    assert cost["protected_text"] == "$524.88"
    risk = a["risk"]
    assert risk["score"] == 87 and sum(p["points"] for p in risk["parts"]) == 86.5  # 86.5 rounds half-up to 87
    assert {p["label"] for p in risk["parts"]} == {"Hidden deadline", "Price jumps", "Hard to cancel",
                                                   "Hard-to-read terms"}
    u = a["usage"]
    assert (u["total"], u["deadline_day"], u["first_charge_day"]) == (2, 7, 11)
    assert [r["opens"] for r in u["rows"][:5]] == [0, 0, 1, 0, 1]


def test_sections(client: TestClient) -> None:
    """U10: Overview · Activity · Emails, one at a time; the check-in is on the card in Overview."""
    subscribe(client)
    advance_to(client, 5)
    html = client.get("/").text
    nav = html.split('data-testid="side-nav"', 1)[1].split("</nav>", 1)[0]
    names = re.findall(r'data-nav="([a-z]+)"', nav)
    assert names == ["overview", "activity", "emails"]
    for name in names:
        panel = re.search(rf'<div class="panel" id="panel-{name}"[^>]*>', html)
        assert panel, name
        assert ("hidden" in panel.group(0)) == (name != "overview"), name  # Overview opens first
    sections = {name: html.split(f'id="panel-{name}"', 1)[1].split('<div class="panel"', 1)[0] for name in names}
    assert 'data-testid="user-protected"' in sections["overview"] and 'data-testid="sub-card"' in sections["overview"]
    assert 'data-testid="user-reminder"' in sections["overview"]
    assert 'data-testid="next-decision"' in sections["overview"]
    assert "Messages to you" in sections["activity"] and 'data-testid="user-history"' in sections["activity"]
    assert "Everything SubGuard did" in sections["activity"] and "Your cancellation emails" in sections["emails"]
    badge = re.search(r'id="live-badge-activity" data-live\s*>(\d+)', html)
    assert badge and int(badge.group(1)) == len(alerts(client))
    assert "/static/user-nav.js" in html

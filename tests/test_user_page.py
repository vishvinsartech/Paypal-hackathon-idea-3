"""Top bar + footer, and Priya's SubGuard at `/` (the product view; FIX_PLAN Phase 3 U1-U12, D-148).
`/user` and `/me` redirect to `/`."""

from __future__ import annotations

import re
from html import unescape

from fastapi.testclient import TestClient

from tests.story_helpers import add_user, advance_to, alerts, cancel_via_alert, on, subscribe

FOOTER = ("footer", "footer-license", "footer-github", "dev-menu", "dev-health", "dev-docs", "health-dots")


def greeting(name: str) -> str:
    return f'Hi <span class="hi-name" data-testid="hi-name">{name}</span>, here’s your dashboard'


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
        for gone in ("health-dots", "/healthz", "/docs", "tab-demo", "tab-user", "view-shop"):
            assert gone not in bar, (url, gone)
        # D-166: Live demo · Priya's dashboard · Demo shops, on every page (the shop in a new tab)
        assert 'href="/?demo=1&amp;user=priya" data-testid="topnav-demo"' in bar
        assert 'data-testid="topnav-dashboard"' in bar and "Priya's dashboard" in bar
        assert 'href="/shop?user=priya" target="_blank" rel="noopener" data-testid="topnav-shop"' in bar
        footer = html.split('data-testid="footer"', 1)[1].split("</footer>", 1)[0]
        for text in ("Fictional merchant", "PayPal Sandbox", ">MIT<", "GitHub", "Developer"):
            assert text in footer, text
        assert "https://github.com/vishvinsartech/Paypal-hackathon-idea-3" in footer
    assert 'data-testid="topnav-dashboard" aria-current="page"' in top_bar(client.get("/").text)
    assert 'data-testid="topnav-demo" aria-current="page"' in top_bar(client.get("/?demo=1").text)
    html = client.get("/").text
    for href in ("/healthz", "/docs"):  # new tabs, so the demo window stays put
        assert re.search(rf'href="{href}"[^>]*target="_blank"', html), href
    toggle = re.search(r'<button[^>]*data-testid="theme-toggle"[^>]*>', html)
    assert toggle and 'aria-label="Switch to light theme"' in toggle.group(0) and "title=" in toggle.group(0)
    assert "theme-label" not in html  # an icon with a tooltip, no "Dark" text (U1)
    assert 'h.dataset.theme = t' in html.split("</head>")[0]  # theme set before first paint
    assert "ag-charts-community" in html and 'data-testid="chart-upcoming"' in html  # D-174: Analytics section
    assert client.get("/healthz").status_code == 200 and client.get("/docs").status_code == 200


def test_old_urls_redirect(client: TestClient) -> None:
    for old in ("/user", "/me", "/user?user=priya"):
        r = client.get(old, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"].startswith("/"), old
    assert client.get("/me?user=priya").url.path == "/"


def test_empty_state(client: TestClient) -> None:
    """U11 / D-174: nothing live yet -> "All clear ✓" and an "Open the demo shop" button; the sample history shows."""
    html = client.get("/").text
    assert 'data-testid="user-dashboard"' in html and greeting("Priya") in html
    assert 'data-testid="user-empty"' in html and "All clear" in html
    assert "When you start a free trial, SubGuard checks it before you pay" in html
    assert re.search(r'href="/shop\?user=priya"[^>]*data-testid="empty-open-shop">Open the demo shop', html)
    for t in ("nav-overview", "nav-subscriptions", "nav-activity", "nav-emails", "nav-analytics", "nav-settings",
              "chat-open"):
        assert f'data-testid="{t}"' in html, t
    for gone in ("subs-grid", "sub-card", "user-reminder", "proof-banner", "chart-cost", "history-grid"):
        assert f'data-testid="{gone}"' not in html, gone


def head(card: str) -> str:
    """The card's headline text (tags stripped)."""
    h = card.split('data-testid="sub-headline">', 1)[1].split("</strong>\n", 1)[0]
    return unescape(re.sub(r"<[^>]+>", "", h))


def line(card: str) -> str:
    """The card's one sub-line (tags stripped)."""
    m = re.search(r'<p class="story-sub" data-testid="(?:sub-line|layer2-waiting)">(.*?)</p>', card, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def nodes(card: str) -> list[tuple[str, str]]:
    """The timeline as (key, state[ is-key]) pairs, in order."""
    return [(k, st.strip()) for st, k in re.findall(r'class="stl-node is-([a-z -]+)" data-testid="tl-([a-z_]+)"', card)]


def plan(card: str) -> str:
    """The "My plan" line under the headline (tags stripped), or ""."""
    m = re.search(r'<span class="my-plan" data-testid="my-plan">(.*?)</span></span>', card, re.S)
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()) if m else ""


def buttons(card: str) -> list[str]:
    acts = card.split('class="story-actions">', 1)[1].split("</div>", 1)[0] if "story-actions" in card else ""
    return re.findall(r'data-testid="([a-z-]+)">', acts)


def test_card_story_states(demo_client: TestClient) -> None:
    """D-169: one headline, one sub-line, at most two buttons per state, and the story timeline."""
    c = demo_client
    main = subscribe(c)
    html = c.get("/").text
    card = card_of(html)
    for gone in ("sub-more", "fact-tiles", "sub-dl", "next-decision", "proof-banner", "user-email-ready",
                 "live-banners", "audit-chain-mini", "user-protected"):  # removed from the Overview
        assert gone not in html, gone
    assert 'data-testid="status-penwright">ACTIVE<' in card  # for screen readers only
    assert re.search(r'data-testid="risk-score">Risk 8\d/100<', card)
    assert '<span class="sub-tile" style="background:#' in card and ">Pw</span>" in card  # D-177: not "PS"
    assert head(card) == f"Free until {on(10)}, then $24.99/month"
    assert re.search(r'<details class="sub-fold" data-sub-details="[^"]+" data-testid="sub-toggle">', card)  # closed
    assert line(card) == "Up to $524.88 this year if you keep it."  # the terms' last day is on See evidence
    assert plan(card) == (f"My plan: I'll check in with you on {on(5)}. No answer? I'll cancel it in PayPal on "
                          f"{on(6)}, a day before your {on(7)} deadline. Change plan")
    assert 'href="#settings" data-go="settings" data-testid="change-plan"' in card
    assert buttons(card) == ["sub-cancel", "sub-keep"]
    assert nodes(card) == [("signup", "done"), ("check_in", "next"), ("auto_cancel", "next"),
                           ("act_by", "next is-key"), ("first_charge", "next")]
    auto = card.split('data-testid="tl-auto_cancel">', 1)[1].split("</li>", 1)[0]
    assert "if no answer" in auto and f'<time class="stl-date">{on(6)}</time>' in auto
    act_by = card.split('data-testid="tl-act_by">', 1)[1].split("</li>", 1)[0]
    assert f'<time class="stl-date">{on(7)}</time>' in act_by
    assert ">Today</span>" in card
    assert f'href="/subscriptions/{main["id"]}?user=priya" data-testid="view-review">See evidence<' in card
    assert f'<code data-testid="paypal-sub-id">{main["paypal_id"]}</code>' in card
    assert "user-reminder" not in html  # no check-in before Day 5

    advance_to(c, 5)
    (check,) = alerts(c, kind="reminder")
    card = card_of(html := c.get("/").text)
    assert 'data-testid="user-reminder"' in card and 'data-testid="sub-toggle" open>' in card  # D-170: opens itself
    assert head(card) == "Keep your Penwright trial?"
    assert line(card) == "You opened it twice in 5 days. SubGuard suggests cancelling; you decide."
    assert plan(card).startswith(f"My plan: I checked in with you on {on(5)}. No answer? I'll cancel it in PayPal")
    assert buttons(card) == ["alert-cancel", "alert-keep"]  # SubGuard's suggestion is the main button
    assert f'class="btn" data-alert="{check["id"]}" data-action="cancel"' in card
    assert "data-sub-keep" not in html and "data-sub-cancel" not in html
    assert html.count('data-action="keep"') == 1 and html.count('data-action="cancel"') == 1  # U8: one pair
    assert ("check_in", "done") in nodes(card)

    cancel_via_alert(c, check)
    card = card_of(html := c.get("/").text)
    assert 'data-testid="status-penwright">CANCELLED<' in card and "user-reminder" not in html
    assert head(card) == "You won't be charged"
    assert plan(card) == f"Cancelled in PayPal on {on(5)}."
    assert line(card) == "$24.99 saved now · up to $524.88 this year"
    assert 'data-testid="card-saved">$24.99<' in card
    assert 'data-testid="risk-score">Risk was ' in card
    assert buttons(card) == ["email-review"]  # her email draft is the one thing left to do
    assert nodes(card) == [("signup", "done"), ("check_in", "done"), ("cancelled", "done is-key"),
                           ("email", "next"), ("first_charge", "blocked")]
    assert "start-new-trial" not in card and "Restart trial" not in html  # D-172: one Penwright per run
    n = c.get("/api/notices?user=priya").json()[0]
    c.post(f"/api/notices/{n['id']}/send", json={"user_id": "priya", "to": n["to"], "subject": n["subject"],
                                                  "body": n["body"]})
    card = card_of(c.get("/").text)
    assert buttons(card) == [] and ("email", "done") in nodes(card)

    advance_to(c, 11)
    card = card_of(html := c.get("/").text)
    assert head(card) == "$24.99 never charged"
    assert line(card) == "PayPal had no active subscription to charge · up to $524.88 saved this year"
    assert nodes(card)[-1] == ("first_charge", "blocked is-key")
    did = html.split('data-testid="audit-summary"', 1)[1].split("</ol>", 1)[0]
    assert did.count('data-testid="audit-summary-row"') == 3  # D-172: the 3 latest Activity entries
    assert "chain verified" not in html.split('id="panel-overview"', 1)[1].split('id="panel-activity"', 1)[0]
    assert "(demo outbox" not in did and "edited:" not in did
    assert did.index("nothing to charge") < did.index("Sent your cancellation email")  # newest first


def test_keep_card_means_no_buttons(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 5)
    assert c.post(f"/api/subscriptions/{main['id']}/keep", json={"user_id": "priya"}).json()["status"] == "kept"
    html = c.get("/").text
    card = card_of(html)
    assert head(card) == "You're keeping Penwright" and "data-sub-keep" not in html and "user-reminder" not in html
    assert plan(card) == "You chose to keep it. I'll stop asking." and "change-plan" not in card
    assert buttons(card) == [] and ("kept", "done is-key") in nodes(card)


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
    assert re.findall(r'data-testid="audit-summary-row" data-kind="(\w+)"', did) == [
        "charge_blocked", "email_sent", "cancel"]  # D-172: the 3 latest Activity entries, same data


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
    assert 'data-testid="user-history"' not in html and 'id="history-grid"' not in html  # D-172: one timeline
    add_user(c)
    assert c.get("/api/subscription-history?user=intruder").json() == []  # R5


def test_user_page_shows_only_her_data(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    add_user(c)
    html = c.get("/?user=intruder").text
    assert greeting("Intruder") in html and 'data-testid="user-empty"' in html
    assert "Penwright Studio" not in html and "Framewise" not in html  # R5: her sample history isn't theirs either
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
    """D-174: Overview · Subscriptions · Activity · Emails · Analytics · Settings, one at a time; the check-in is
    on Penwright's card under "Needs your attention"."""
    subscribe(client)
    advance_to(client, 5)
    html = client.get("/").text
    nav = html.split('data-testid="side-nav"', 1)[1].split("</nav>", 1)[0]
    names = list(dict.fromkeys(re.findall(r'data-nav="([a-z]+)"', nav)))
    assert names == ["overview", "subscriptions", "activity", "emails", "analytics", "settings"]
    for name in names:
        panel = re.search(rf'<div class="panel" id="panel-{name}"[^>]*>', html)
        assert panel, name
        assert ("hidden" in panel.group(0)) == (name != "overview"), name  # Overview opens first
    sections = {name: html.split(f'id="panel-{name}"', 1)[1].split('<div class="panel"', 1)[0] for name in names}
    assert 'data-testid="sub-card"' in sections["overview"] and 'data-testid="user-reminder"' in sections["overview"]
    assert 'data-testid="audit-summary"' in sections["overview"]  # D-169: the right column is What SubGuard did
    for gone in ("Messages to you", "user-history", "Everything SubGuard did"):  # D-172: one timeline instead
        assert gone not in sections["activity"], gone
    assert 'data-testid="activity-list"' in sections["activity"] and "Your cancellation emails" in sections["emails"]
    badge = re.search(r'id="live-badge-activity" data-live\s*>(\d+)', html)
    assert badge and int(badge.group(1)) == 1  # the open check-in waits for her answer
    assert "/static/user-nav.js" in html


def test_live_demo_page_is_separate_and_asks_for_priya(demo_client: TestClient) -> None:
    """D-167: `/?demo=1` is only the Live demo: controls, the story, Priya's side (her check-in, answered here)."""
    c = demo_client
    subscribe(c)
    html = c.get("/?demo=1").text
    assert 'data-testid="live-demo"' in html and 'data-testid="user-dashboard"' not in html
    assert "sub-card" not in html and 'data-testid="demo-priya-empty"' in html  # nothing to answer before Day 5
    advance_to(c, 5)
    (check,) = alerts(c, kind="reminder")
    html = c.get("/?demo=1").text
    side = html.split('data-testid="demo-priya"', 1)[1].split("</section>", 1)[0]
    assert "Keep it or cancel?" in side and "SubGuard suggests: cancel. You decide." in side
    for action in ("keep", "cancel"):  # U8: still exactly one pair on screen
        assert html.count(f'data-alert="{check["id"]}" data-action="{action}"') == 1
    assert "Check-in: keep it or cancel?" in side  # the subscription list line


def test_my_plan_with_auto_cancel_off(demo_client: TestClient) -> None:
    """D-177: Settings off -> the plan promises a second reminder on the Act by day (and it is sent), no
    Auto-cancel step on the timeline."""
    c = demo_client
    assert c.post("/api/settings", json={"user_id": "priya", "auto_cancel_trials": False, "auto_send_notice": False,
                                         "remind_by_email": True}).status_code == 200
    subscribe(c)
    card = card_of(c.get("/").text)
    assert plan(card) == (f"My plan: I'll check in with you on {on(5)} and remind you again on {on(7)}. "
                          "I won't cancel without you. Change plan")
    assert "auto_cancel" not in [k for k, _ in nodes(card)]
    html = c.get("/").text  # Activity doesn't claim a cancel that won't happen (R7)
    assert f"Set a check-in for {on(5)}: auto-cancel is off, so you decide" in html and "cancels on" not in html
    advance_to(c, 6)
    assert not alerts(c, kind="act_by_reminder")
    advance_to(c, 7)
    (rem,) = alerts(c, kind="act_by_reminder")
    assert rem["title"] == "Penwright: today is your last day to cancel" and "Auto-cancel is off" in rem["body"]

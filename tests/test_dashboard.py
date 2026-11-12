"""D-174: Priya's dashboard with a sidebar. Sample history (read-only, labelled), live rows (labelled), Overview
(Penwright first, Coming up, Saved so far), the Subscriptions list, Analytics numbers, and Settings -> consent."""

from __future__ import annotations

import hashlib
import re

from fastapi.testclient import TestClient

from tests.story_helpers import advance_to, alerts, audit, cancel_via_alert, sub, subscribe

SAMPLES = ("Framewise", "Lumen Notes", "Stillwater Audio")


def rows(html: str) -> list[str]:
    part = html.split('data-testid="subs-list"', 1)[1].split("</ul>", 1)[0]
    return part.split('data-testid="subs-row"')[1:]


def panel(html: str, name: str) -> str:
    return html.split(f'id="panel-{name}"', 1)[1].split('<div class="panel"', 1)[0]


def count(html: str, group: str) -> int:
    m = re.search(rf'id="live-count-{group}" data-live>(\d+)<', html)
    assert m, group
    return int(m.group(1))


def test_sample_history_is_labelled_and_read_only(client: TestClient, data_dir) -> None:  # noqa: ANN001
    seed = data_dir / "seed" / "sample_history.json"
    before = hashlib.sha256(seed.read_bytes()).hexdigest()
    html = client.get("/").text
    r = rows(html)
    assert [x.split('data-merchant="', 1)[1].split('"', 1)[0] for x in r] == list(SAMPLES)
    assert all("Sample history" in x for x in r)
    framewise, lumen, still = r
    assert "$12/mo" in framewise and "Risk 15" in framewise and "Yesterday" in framewise and "In use" in framewise
    assert "Sep 8" in lumen and "price rise from $12 to $19" in lumen and "Saved $84 a year" in lumen
    assert "Oct 3" in still and "before the first charge" in still and "Saved $14.99" in still
    assert (count(html, "all"), count(html, "in_use"), count(html, "trial"), count(html, "cancelled")) == (3, 1, 0, 2)
    # Start demo / Reset never touch it: it isn't runtime data
    subscribe(client)
    assert client.post("/api/demo/reset").status_code == 200
    assert hashlib.sha256(seed.read_bytes()).hexdigest() == before
    assert [x for x in SAMPLES if x in client.get("/").text] == list(SAMPLES)


def test_penwright_first_in_overview_and_live_label(client: TestClient) -> None:
    subscribe(client)
    subscribe(client, merchant="quillnote", plan_key="quillnote-plus")  # signed up later, still second
    html = client.get("/").text
    over = panel(html, "overview")
    cards = re.findall(r'data-testid="sub-card" data-sub="[^"]+"', over)
    assert cards and "Penwright Studio" in over.split('data-testid="sub-card"', 2)[1]
    assert over.index("Needs your attention") < over.index("Coming up") < over.index("Saved so far") \
        < over.index("Recent activity")
    live = [x for x in rows(html) if "src-live" in x]
    assert [x.split('data-merchant="', 1)[1].split('"', 1)[0] for x in live] == ["Penwright Studio", "Quillnote"]
    assert all("Live demo · simulated PayPal" in x for x in live)  # mock mode doesn't claim the sandbox (R7)
    assert "Free trial" in live[0] and count(html, "trial") == 2
    up = re.findall(r'data-testid="coming-up-row">.*?</li>', over, flags=re.S)
    assert len(up) == 3 and "Penwright Studio" in "".join(up) and "$24.99" in "".join(up)
    # the same three in the sidebar; a live trial's first charge is flagged (danger colour)
    side = re.findall(r'data-testid="side-coming-up-row">.*?</li>', html, flags=re.S)
    assert [x.replace("side-coming-up-row", "coming-up-row") for x in side] == up
    pen = [x for x in re.findall(r'<li class="up-row[^"]*" data-testid="side-coming-up-row">.*?</li>', html, flags=re.S)
           if "Penwright Studio" in x]
    assert pen and pen[0].startswith('<li class="up-row up-danger"') and "first charge" in pen[0]
    assert "No surprise charges. That’s the plan" in html and 'data-testid="side-toggle"' in html


def test_saved_so_far_and_analytics(demo_client: TestClient) -> None:
    c = demo_client
    a = c.get("/api/dashboard/analytics").json()
    assert a["saved"]["rows"] == [{"kind": "Trials stopped", "amount": "14.99"},
                                  {"kind": "Price rises avoided", "amount": "84.00"}]
    assert len(a["monthly"]["rows"]) == 6 and a["monthly"]["series"] == ["Framewise", "Lumen Notes"]
    assert 'data-testid="saved-total">$98.99<' in c.get("/").text
    main = subscribe(c)
    assert "Penwright Studio" in c.get("/api/dashboard/analytics").json()["upcoming"]["series"]
    advance_to(c, 5)
    cancel_via_alert(c, alerts(c, kind="reminder")[0])
    assert sub(c, main["id"])["status"] == "CANCELLED"
    a = c.get("/api/dashboard/analytics").json()
    assert a["saved"]["rows"][0]["amount"] == "39.98" and a["saved"]["total"] == "$123.98"  # + Penwright's $24.99
    assert "Penwright Studio" not in a["upcoming"]["series"]
    html = c.get("/").text
    assert 'data-testid="saved-total">$123.98<' in html
    pen = next(x for x in rows(html) if 'data-merchant="Penwright Studio"' in x)
    assert "Cancelled" in pen and "Saved $24.99" in pen and 'data-testid="subs-ended"' in pen


def test_intruder_sees_no_samples(client: TestClient) -> None:
    from tests.story_helpers import add_user, as_user
    as_user(client, add_user(client))
    a = client.get("/api/dashboard/analytics?user=intruder").json()
    assert a["saved"]["total"] == "$0" and a["monthly"]["series"] == []


def test_settings_map_to_consent(client: TestClient) -> None:
    html = client.get("/").text
    s = panel(html, "settings")
    for text in ("Cancel trials automatically if I don't answer", "Send the cancellation email for me", "Remind me by"):
        assert text.replace("'", "&#39;") in s or text in s, text
    assert re.search(r'data-testid="settings-auto-cancel"\s+checked', s)
    assert not re.search(r'data-testid="settings-auto-send"\s+checked', s)
    res = client.post("/api/settings", json={"user_id": "priya", "auto_cancel_trials": False,
                                             "auto_send_notice": True, "remind_by_email": False})
    assert res.status_code == 200 and "email" not in res.json()["settings"]["channels"]
    assert audit(client, "settings_changed")
    pre = client.post("/api/review/preflight", json={"merchant_url": "/shop/penwright", "plan_key": "penwright-pro",
                                                     "user_id": "priya"}).json()
    assert pre["auto_send_default"] is True  # pre-ticks the companion's box
    main = subscribe(client)
    timer_set = alerts(client, kind="timer_set")[0]
    assert "won't cancel without your answer" in timer_set["body"]
    advance_to(client, 7)  # past the Day 6 safety timer, no answer
    assert sub(client, main["id"])["status"] == "ACTIVE"
    blocked = [e for e in audit(client, rule_id="R2", decision="blocked") if "Settings" in (e.get("reason") or "")]
    assert blocked  # R2 blocked the auto-cancel because she turned it off


def test_top_bar_presenter_menu(client: TestClient) -> None:
    html = client.get("/").text
    bar = html.split('<header class="topbar"', 1)[1].split("</header>", 1)[0]
    menu = bar.split('data-testid="topnav-presenter"', 1)[1].split("</details>", 1)[0]
    assert 'data-testid="topnav-demo"' in menu and 'data-testid="topnav-shop"' in menu
    avatar = bar.split('class="menu avatar-menu"', 1)[1].split("</details>", 1)[0]
    assert 'data-testid="avatar-emails"' in avatar and 'data-testid="avatar-settings"' in avatar

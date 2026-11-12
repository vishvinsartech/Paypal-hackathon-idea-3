"""Phase 7 Step 2 (D-181): `/` is the intro when signed out and the dashboard when signed in; the sign-in page."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routes.landing import landing_view
from tests.story_helpers import TEST_PASSWORD


def test_signed_out_home_is_the_intro(anon_client: TestClient, settings: Settings) -> None:
    res = anon_client.get("/", follow_redirects=False)
    assert res.status_code == 200
    html = res.text
    for testid in ("intro", "hero", "how-it-works", "intro-ai", "intro-signin", "intro-shops", "intro-fictional",
                   "topnav-shops", "topnav-signin", "brand", "mode-badge"):
        assert f'data-testid="{testid}"' in html, testid
    assert "AI reads the fine print. PayPal enforces the outcome." in html
    assert "only with your OK or a safety timer you saw" in html
    assert "Code, not the AI, makes every decision." in html
    assert "Fictional merchant for the SubGuard demo." in html
    assert 'href="/login"' in html and 'href="/shop"' in html
    # signed out: no Presenter menu, no dashboard link, no avatar, no chat, no dashboard data
    for gone in ("topnav-presenter", "topnav-dashboard", "user-avatar", "chat-open", 'id="chat"', "side-nav",
                 "data-user="):
        assert gone not in html, gone
    v = landing_view(settings)
    for value in (v["intro"], v["step_up"], f"Day {v['terms_last_day']}", f"{v['trial_days']}-day"):
        assert value in html, value


def test_intro_numbers_come_from_settings(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    for k, val in {"PENWRIGHT_INTRO_PRICE": "29.99", "PENWRIGHT_STEP_UP_PRICE": "59.99",
                   "PENWRIGHT_NOTICE_DAYS": "4"}.items():
        monkeypatch.setenv(k, val)
    s = Settings(_env_file=None, app_mode="mock", data_dir=data_dir, demo_password=TEST_PASSWORD)  # type: ignore[call-arg]
    with TestClient(create_app(s)) as c:
        html = c.get("/").text
    assert "$29.99" in html and "$59.99" in html and "cancel 4 days before" in html
    assert "24.99" not in html and "49.99" not in html


def test_signed_in_home_is_the_dashboard(client: TestClient) -> None:
    html = client.get("/").text
    assert 'data-testid="intro"' not in html and 'data-testid="side-nav"' in html
    assert 'data-testid="topnav-presenter"' in html and 'data-testid="topnav-signin"' not in html


def test_live_demo_still_needs_sign_in(anon_client: TestClient) -> None:
    for url in ("/?demo=1", "/?demo=1&user=priya"):
        res = anon_client.get(url, follow_redirects=False)
        assert res.status_code == 303 and res.headers["location"].startswith("/login?next="), url
    assert anon_client.get("/?demo=0", follow_redirects=False).status_code == 200  # the intro


def test_login_page(anon_client: TestClient) -> None:
    html = anon_client.get("/login").text
    assert '<label for="email">Email</label>' in html and '<label for="password">Password</label>' in html
    assert 'href="/static/auth.css"' in html and 'data-testid="login-back"' in html and 'href="/"' in html
    assert "Demo account: Priya" in html and TEST_PASSWORD not in html
    assert "sign up" not in html.lower() and "topnav-presenter" not in html
    res = anon_client.post("/login", data={"email": "priya@subguard-demo.example", "password": "nope"})
    assert 'data-testid="login-error"' in res.text and 'role="alert"' in res.text


def test_auth_css_sizes() -> None:
    css = (Path(__file__).resolve().parent.parent / "app" / "static" / "auth.css").read_text(encoding="utf-8")
    assert "font: 16px" in css  # no zoom-on-focus on phones
    assert css.count("min-height: 44px") >= 2  # input and button tap targets

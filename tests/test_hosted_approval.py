"""D-192: the hosted live demo. Server-side auto-approve only where it can run; elsewhere the Penwright window shows
PayPal's own button (plus, if allowed, the sandbox buyer's login) and onApprove registers through /register, which
checks the subscription with PayPal and never trusts the browser.

The mock PayPal stands in for the sandbox (the app is flipped to sandbox mode after start-up, keeping the mock).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import ROOT_DIR, Settings
from app.hosts import browser_available as real_browser_available
from app.hosts import can_auto_approve, show_sandbox_buyer
from app.main import create_app
from tests.story_helpers import audit, sign_in

EMAIL = "priya-buyer@personal.example"
PASSWORD = "Pl4y-M0ney-Only!"
OLD_TEXT = "only runs on a local SubGuard"


def req(host: str) -> Request:
    return Request({"type": "http", "scheme": "http", "server": (host, 80), "path": "/", "headers": [],
                    "query_string": b""})


def make(settings: Settings, base_url: str, **values: Any) -> TestClient:
    c = TestClient(create_app(settings), base_url=base_url)
    c.__enter__()
    sign_in(c)
    s = c.app.state.services.settings  # type: ignore[attr-defined]
    s.app_mode = "sandbox"
    for k, v in {"paypal_sandbox_buyer_email": EMAIL, "paypal_sandbox_buyer_password": PASSWORD, **values}.items():
        setattr(s, k, v)
    return c


@pytest.fixture
def hosted(settings: Settings) -> Iterator[TestClient]:
    c = make(settings, "https://subguard-demo.onrender.com", show_sandbox_buyer=True)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def local(settings: Settings) -> Iterator[TestClient]:
    c = make(settings, "http://127.0.0.1:8000", show_sandbox_buyer=True)
    yield c
    c.__exit__(None, None, None)


# ---- can_auto_approve() ------------------------------------------------------------------------------------
def test_auto_detects_a_local_machine(settings: Settings) -> None:
    assert can_auto_approve(settings, req("127.0.0.1")) and can_auto_approve(settings)
    assert not can_auto_approve(settings, req("subguard-demo.onrender.com"))


def test_render_env_means_hosted(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    assert not can_auto_approve(settings, req("127.0.0.1")) and not can_auto_approve(settings)


def test_no_browser_means_manual(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.hosts

    monkeypatch.setattr(app.hosts, "browser_available", lambda: False)
    assert not can_auto_approve(settings, req("127.0.0.1"))


@pytest.mark.parametrize(("mode", "expected"), [("auto", True), ("manual", False), ("off", False)])
def test_auto_approve_mode(settings: Settings, mode: str, expected: bool) -> None:
    settings.auto_approve_mode = mode  # type: ignore[assignment]
    assert can_auto_approve(settings, req("127.0.0.1")) is expected


def test_browser_available_needs_a_display_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.hosts

    monkeypatch.setattr(app.hosts.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert real_browser_available() is False


def test_show_sandbox_buyer_rules(settings: Settings) -> None:
    settings.paypal_sandbox_buyer_email, settings.paypal_sandbox_buyer_password = EMAIL, PASSWORD
    settings.show_sandbox_buyer = True
    assert not show_sandbox_buyer(settings)  # mock mode: never
    settings.app_mode = "sandbox"
    assert show_sandbox_buyer(settings)
    settings.auto_approve_mode = "off"
    assert not show_sandbox_buyer(settings)
    settings.auto_approve_mode = "auto"
    settings.show_sandbox_buyer = False
    assert not show_sandbox_buyer(settings)


# ---- the Penwright window ----------------------------------------------------------------------------------
def test_hosted_window_shows_the_buyer_card(hosted: TestClient) -> None:
    html = hosted.get("/shop/penwright?user=priya&autodemo=1").text
    assert 'data-manual-approve="1"' in html and 'data-buyer-card="1"' in html
    assert 'data-buyer-login="1"' not in html
    card = html.split('data-testid="sandbox-buyer-card"', 1)[1].split('id="paypal-area"', 1)[0]
    assert "Log in to PayPal with this sandbox test buyer" in card and EMAIL in card and PASSWORD in card
    assert "Sandbox test account, play money only." in card and card.count('class="buyer-copy"') == 2
    assert html.index('data-testid="sandbox-buyer-card"') < html.index('id="paypal-area"')  # above Subscribe
    assert 'data-subguard-ignore data-testid="sandbox-buyer-card"' in html  # never sent to the LLM review
    js = hosted.get("/shop/static/autodemo.js").text
    assert ("Click Subscribe with PayPal and log in with the sandbox buyer above. "
            "This window closes after you approve.") in js
    assert OLD_TEXT not in html


def test_credentials_only_in_the_autodemo_window(hosted: TestClient) -> None:
    for url in ("/shop/penwright", "/shop/penwright?user=priya", "/shop/quillnote", "/shop", "/", "/?demo=1",
                "/healthz", "/api/review/preflight"):
        text = hosted.get(url).text
        assert PASSWORD not in text and EMAIL not in text, url


def test_hosted_without_show_flag_hides_credentials(hosted: TestClient) -> None:
    hosted.app.state.services.settings.show_sandbox_buyer = False  # type: ignore[attr-defined]
    html = hosted.get("/shop/penwright?user=priya&autodemo=1").text
    assert 'data-manual-approve="1"' in html and 'data-buyer-card="1"' not in html
    assert PASSWORD not in html and EMAIL not in html
    assert "Click Subscribe with PayPal and log in with your PayPal sandbox buyer account." in html


def test_local_window_is_unchanged(local: TestClient) -> None:
    html = local.get("/shop/penwright?user=priya&autodemo=1").text
    assert 'data-buyer-login="1"' in html and "data-manual-approve" not in html
    assert "sandbox-buyer-card" not in html and PASSWORD not in html and EMAIL not in html
    js = local.get("/shop/static/autodemo.js").text
    assert "Live demo: this window plays Priya. Confirm the order in PayPal; this window then closes by itself." in js


def test_mock_mode_has_no_card(client: TestClient) -> None:
    client.app.state.services.settings.show_sandbox_buyer = True  # type: ignore[attr-defined]
    html = client.get("/shop/penwright?user=priya&autodemo=1").text
    assert "data-manual-approve" not in html and "sandbox-buyer-card" not in html


def test_old_local_only_text_is_gone() -> None:
    hits = []
    for folder in ("app", "shop", "docs", "scripts", "demo-video"):
        root = ROOT_DIR / folder
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".js", ".html", ".md", ".json", ".txt"} \
                    and "vendor" not in path.parts and "archive" not in path.parts:
                if OLD_TEXT in path.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(path))
    assert hits == []


def test_checkout_script_wires_the_paypal_button(hosted: TestClient) -> None:
    js = hosted.get("/shop/static/checkout_sandbox.js").text
    assert 'area.dataset.manualApprove === "1"' in js and "paypal.Buttons" in js
    assert "js_sdk: true" in js and "data.subscriptionID" in js and "/api/subscriptions/register" in js
    assert "You closed PayPal before approving. Click Subscribe with PayPal to try again." in (
        js.replace('." + TRY_AGAIN', '. Click Subscribe with PayPal to try again.'))
    assert "Subscribed. You can close this window." in js and "debug_id" in js
    dash = hosted.get("/static/autoplay_sandbox.js").text
    assert "ev.origin !== location.origin" in dash and "/api/subscriptions?user=" in dash


# ---- /api/subscriptions/register: the backend checks PayPal, not the browser --------------------------------
def create_approved(c: TestClient, merchant: str = "penwright", plan_key: str = "penwright-pro") -> str:
    created = c.post("/api/checkout/create", json={"merchant_id": merchant, "plan_key": plan_key,
                                                   "user_id": "priya", "js_sdk": True}).json()
    c.app.state.services.settings.app_mode = "mock"  # type: ignore[attr-defined]  # mock-approve is mock-only
    c.post("/api/checkout/mock-approve", json={"paypal_id": created["paypal_id"]})
    c.app.state.services.settings.app_mode = "sandbox"  # type: ignore[attr-defined]
    return created["paypal_id"]


def register(c: TestClient, paypal_id: str, plan_key: str = "penwright-pro") -> Any:
    return c.post("/api/subscriptions/register", json={"paypal_id": paypal_id, "merchant_id": "penwright",
                                                       "plan_key": plan_key, "user_id": "priya"})


def test_active_is_recorded_and_audited(hosted: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    pid = create_approved(hosted)
    res = register(hosted, pid)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ACTIVE" and res.json()["paypal_id"] == pid
    assert [s["paypal_id"] for s in hosted.get("/api/subscriptions?user=priya").json()] == [pid]
    assert audit(hosted, "subscription_registered")[0]["details"]["paypal_id"] == pid
    everything = res.text + hosted.get("/api/audit-log").text + hosted.get("/healthz").text + caplog.text
    everything += (hosted.app.state.services.settings.runtime_dir / "audit_log.jsonl").read_text(encoding="utf-8")  # type: ignore[attr-defined]
    assert PASSWORD not in everything and EMAIL not in everything


def test_wrong_plan_is_rejected(hosted: TestClient) -> None:
    pid = create_approved(hosted, "quillnote", "quillnote-plus")
    res = register(hosted, pid)
    assert res.status_code == 409 and "isn't for this plan" in res.json()["error"]
    assert hosted.get("/api/subscriptions?user=priya").json() == []
    (row,) = audit(hosted, "subscription_register_rejected")
    assert row["decision"] == "blocked" and row["details"]["paypal_id"] == pid
    assert PASSWORD not in res.text


def test_not_yet_active_is_not_recorded(hosted: TestClient) -> None:
    created = hosted.post("/api/checkout/create", json={"merchant_id": "penwright", "plan_key": "penwright-pro",
                                                        "user_id": "priya", "js_sdk": True}).json()
    res = register(hosted, created["paypal_id"])  # never approved: APPROVAL_PENDING
    assert res.status_code == 202 and res.json()["registered"] is False
    assert hosted.get("/api/subscriptions?user=priya").json() == []


def test_duplicate_subscription_id_is_idempotent(hosted: TestClient) -> None:
    pid = create_approved(hosted)
    first, second = register(hosted, pid), register(hosted, pid)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(hosted.get("/api/subscriptions?user=priya").json()) == 1
    assert len(audit(hosted, "subscription_registered")) == 1
    assert len(audit(hosted, "consent_snapshot")) == 1
    assert len(audit(hosted, "subscription_register_repeat")) == 1
    timers = [t for t in hosted.get("/api/timers?user=priya").json() if t["subscription_id"] == first.json()["id"]]
    assert len(timers) == 1

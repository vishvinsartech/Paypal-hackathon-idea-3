"""Phase 7 Step 7: nothing the app serves assumes 127.0.0.1:8000; the sandbox buyer window is local-only (D-183)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT_DIR, Settings
from app.hosts import is_local, server_url
from app.main import create_app
from app.routes.subscriptions import HOSTED_NO_WINDOW
from tests.story_helpers import sign_in

BUYER = {"paypal_sandbox_buyer_email": "buyer@personal.example", "paypal_sandbox_buyer_password": "pw"}


@pytest.fixture
def hosted_sandbox(settings: Settings) -> Iterator[TestClient]:
    """Sandbox mode with the buyer in .env, reached on a public https host like Render."""
    with TestClient(create_app(settings), base_url="https://subguard-demo.onrender.com") as c:
        sign_in(c)
        s = c.app.state.services.settings  # type: ignore[attr-defined]
        s.app_mode = "sandbox"
        for k, v in BUYER.items():
            setattr(s, k, v)
        yield c


def test_hosted_refuses_the_buyer_window(hosted_sandbox: TestClient) -> None:
    res = hosted_sandbox.post("/api/checkout/demo-paypal-window", json={"user_id": "priya"})
    assert res.status_code == 400 and res.json()["detail"] == HOSTED_NO_WINDOW
    assert "local" in HOSTED_NO_WINDOW and "PayPal button" in HOSTED_NO_WINDOW


def test_hosted_shop_uses_paypal_own_page(hosted_sandbox: TestClient) -> None:
    """No buyer-login flag on a public host, so the shop goes to PayPal's own approval page."""
    assert 'data-buyer-login="1"' not in hosted_sandbox.get("/shop/penwright").text


def test_is_local() -> None:
    from starlette.requests import Request

    def req(host: str) -> Request:
        return Request({"type": "http", "scheme": "http", "server": (host, 80), "path": "/", "headers": [],
                        "query_string": b""})
    assert is_local(req("127.0.0.1")) and is_local(req("localhost"))
    assert not is_local(req("subguard-demo.onrender.com")) and not is_local(req("testserver"))


def test_server_url(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert server_url(settings) == f"http://{settings.app_host}:{settings.app_port}/"
    monkeypatch.setenv("PORT", "10000")
    assert server_url(settings) == f"http://{settings.app_host}:10000/"
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://subguard-demo.onrender.com/")
    assert server_url(settings) == "https://subguard-demo.onrender.com/"


def test_no_hardcoded_local_host_in_served_code() -> None:
    """Only the local-only sandbox buyer window may name 127.0.0.1:8000 (D-183); config holds the local defaults."""
    allowed = {ROOT_DIR / "app" / "integrations" / "sandbox_buyer.py", ROOT_DIR / "app" / "config.py",
               ROOT_DIR / "app" / "hosts.py"}
    hits = []
    for folder in ("app", "shop"):
        for path in (ROOT_DIR / folder).rglob("*"):
            if path.suffix not in {".py", ".js", ".html", ".css"} or path in allowed or "vendor" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits += [f"{path.name}: {s}" for s in ("127.0.0.1", "localhost:", ":8000") if s in text]
    assert hits == []

"""Start demo in sandbox mode (D-116/D-117): Penwright window -> companion -> the presenter clicks Subscribe ->
PayPal's page opens logged in as the sandbox buyer -> the presenter confirms -> registered.

The mock PayPal stands in for the sandbox here and the PayPal window is faked; the real path is checked by hand.
The app is flipped to sandbox mode after start-up, keeping the mock gateway.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.integrations.sandbox_buyer as buyer
from app.config import Settings
from app.integrations.paypal_gateway import Ctx
from app.main import create_app
from tests.story_helpers import audit

BUYER = {"paypal_sandbox_buyer_email": "buyer@personal.example", "paypal_sandbox_buyer_password": "pw"}


@pytest.fixture
def sandbox_client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        c.app.state.services.settings.app_mode = "sandbox"  # type: ignore[attr-defined]
        yield c


def set_buyer(c: TestClient, **values: str) -> None:
    for k, v in {**BUYER, **values}.items():
        setattr(c.app.state.services.settings, k, v)  # type: ignore[attr-defined]


def fake_window(c: TestClient, outcome: str = "approved") -> list[dict[str, Any]]:
    """Replace PayPal's window: on "approved", approve the newest pending mock subscription, as the presenter's
    confirmation would."""
    calls: list[dict[str, Any]] = []
    gw = c.app.state.services.gw  # type: ignore[attr-defined]

    async def open_for_confirmation(url: str, email: str, password: str, **kw: Any) -> str:
        calls.append({"url": url, "email": email, **kw})
        if outcome == "approved":
            state = c.app.state.services.store.load("mock_paypal")  # type: ignore[attr-defined]
            pending = [s for s in state.subscriptions.values() if s.status == "APPROVAL_PENDING"]
            await gw.mock_approve(pending[-1].id, Ctx(actor="user"))
        return outcome

    buyer.open_for_confirmation = open_for_confirmation  # type: ignore[assignment]  # restored by the fixture
    return calls


@pytest.fixture(autouse=True)
def restore_buyer() -> Iterator[None]:
    original = buyer.open_for_confirmation
    yield
    buyer.open_for_confirmation = original  # type: ignore[assignment]


def start(c: TestClient, **body: Any) -> Any:
    return c.post("/api/checkout/demo-paypal-window", json={"user_id": "usera", **body})


def test_mock_mode_refuses(client: TestClient) -> None:
    res = start(client)
    assert res.status_code == 400 and "sandbox mode" in res.text


def test_needs_the_buyer_account(sandbox_client: TestClient) -> None:
    set_buyer(sandbox_client, paypal_sandbox_buyer_password="")
    res = start(sandbox_client)
    assert res.status_code == 400 and "PAYPAL_SANDBOX_BUYER_EMAIL" in res.text


def test_confirmed_in_paypal_window_registers(sandbox_client: TestClient) -> None:
    c = sandbox_client
    set_buyer(c)
    calls = fake_window(c)
    review = c.post("/api/review/preflight", json={"merchant_url": "/shop/penwright", "plan_key": "penwright-pro",
                                                   "user_id": "usera"}).json()
    res = start(c, review_id=review["review_id"])
    assert res.status_code == 200, res.text
    sub = res.json()
    assert sub["status"] == "ACTIVE" and sub["owner_id"] == "usera" and sub["merchant_id"] == "penwright"
    (call,) = calls
    assert call["email"] == "buyer@personal.example" and call["timeout_s"] >= 120
    (timer,) = [t for t in c.get("/api/timers?user=usera").json() if t["subscription_id"] == sub["id"]]
    assert (timer["reminder_day"], timer["fire_day"]) == (5, 6)
    (row,) = audit(c, "demo_paypal_window")
    assert row["result"] == "ok" and row["details"]["paypal_id"] == sub["paypal_id"]
    assert row["details"]["buyer"] == "b***@personal.example" and "pw" not in str(row)
    assert audit(c, "paypal_subscription_created")


@pytest.mark.parametrize(("outcome", "text"), [("closed", "window was closed"), ("cancelled", "Cancel and return"),
                                               ("timeout", "5 minutes")])
def test_not_confirmed_registers_nothing(sandbox_client: TestClient, outcome: str, text: str) -> None:
    c = sandbox_client
    set_buyer(c)
    fake_window(c, outcome)
    res = start(c)
    assert res.status_code == 409 and text in res.json()["error"] and res.json()["outcome"] == outcome
    assert c.get("/api/subscriptions?user=usera").json() == []
    assert audit(c, "demo_paypal_window")[0]["result"] == f"not_confirmed:{outcome}"


def test_pages_wire_the_sandbox_start(sandbox_client: TestClient) -> None:
    c = sandbox_client
    html = c.get("/?demo=1").text
    btn = html.split('id="demo-start"', 1)[1].split(">", 1)[0]
    assert 'data-sandbox="1"' in btn and "disabled" not in btn
    assert html.index("/static/autoplay_sandbox.js") < html.index("/static/autoplay.js")
    assert "already logged in as the sandbox buyer" in html
    shop = c.get("/shop/penwright").text
    assert shop.index("/shop/static/autodemo.js") < shop.index("/shop/static/checkout_sandbox.js")
    js = c.get("/shop/static/autodemo.js").text
    assert 'get("autodemo") !== "1"' in js and "window.close()" in js and "location.origin" in js
    checkout = c.get("/shop/static/checkout_sandbox.js").text
    assert "demo-paypal-window" in checkout and 'b.textContent = "Subscribe with PayPal"' in checkout
    assert "consent" not in c.get("/shop/static/autodemo.js").text.lower()  # the presenter confirms, not a script
    assert "subguard:review" in c.get("/static/companion.js").text


def test_mock_mode_start_is_unchanged(client: TestClient) -> None:
    html = client.get("/?demo=1").text
    assert "data-sandbox" not in html.split('id="demo-start"', 1)[1].split(">", 1)[0]
    assert "autodemo.js" not in client.get("/shop/penwright").text


def test_scripted_usage_is_seeded_in_sandbox_too(data_dir: Any) -> None:
    """The live demo's check-in says "opened it twice" in both modes (the seed never touches PayPal)."""
    import asyncio

    from app.core.demo_seed import seed_demo

    s = Settings(_env_file=None, app_mode="mock", data_dir=data_dir, demo_seed=True)  # type: ignore[call-arg]
    with TestClient(create_app(s)) as c:
        svc = c.app.state.services  # type: ignore[attr-defined]
        c.post("/api/demo/reset")
        svc.settings.app_mode = "sandbox"
        with svc.store.edit("state") as state:
            state.demo_seeded = False
        with svc.store.edit("usage") as usage:
            usage.items = []
        assert asyncio.run(seed_demo(svc)) is True
        assert sorted(e.day for e in svc.store.load("usage").items) == [2, 4]


def test_no_usage_reads_naturally(client: TestClient) -> None:
    from tests.story_helpers import advance_to, alerts, subscribe

    subscribe(client)
    advance_to(client, 5)
    (check,) = alerts(client, kind="reminder")
    assert "You haven't opened it yet." in check["body"] and "opened it never" not in check["body"]
    html = client.get("/user").text
    assert "Not opened in 5 days." in html and "You haven&#39;t opened it in 5 days" in html  # Jinja escapes '

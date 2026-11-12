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
from tests.story_helpers import TEST_PASSWORD, audit, sign_in

BUYER = {"paypal_sandbox_buyer_email": "buyer@personal.example", "paypal_sandbox_buyer_password": "pw"}


@pytest.fixture
def sandbox_client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as c:  # the window is local-only (D-183)
        sign_in(c)
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
    return c.post("/api/checkout/demo-paypal-window", json={"user_id": "priya", **body})


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
                                                   "user_id": "priya"}).json()
    res = start(c, review_id=review["review_id"])
    assert res.status_code == 200, res.text
    sub = res.json()
    assert sub["status"] == "ACTIVE" and sub["owner_id"] == "priya" and sub["merchant_id"] == "penwright"
    (call,) = calls
    assert call["email"] == "buyer@personal.example" and call["timeout_s"] >= 120
    (timer,) = [t for t in c.get("/api/timers?user=priya").json() if t["subscription_id"] == sub["id"]]
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
    assert c.get("/api/subscriptions?user=priya").json() == []
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

    s = Settings(_env_file=None, app_mode="mock", data_dir=data_dir, demo_seed=True,  # type: ignore[call-arg]
                 demo_password=TEST_PASSWORD)
    with TestClient(create_app(s)) as c:
        sign_in(c)
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
    assert "You haven&#39;t opened it in 5 days." in html  # D-169 card sub-line; Jinja escapes '


def test_playwright_helpers_work_under_a_selector_loop() -> None:
    """`uvicorn --reload` on Windows serves on a SelectorEventLoop, which can't start subprocesses (Playwright's
    driver). run_on_own_loop gives the coroutine its own loop in a thread, so it works there too (D-117)."""
    import asyncio
    import sys

    from app.integrations.own_loop import run_on_own_loop

    async def spawn() -> str:
        proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "print('hi')",
                                                    stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        return out.decode().strip()

    async def server() -> str:
        return await run_on_own_loop(spawn)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        assert runner.run(server()) == "hi"


def test_manual_shop_visit_logs_in_as_buyer(sandbox_client: TestClient) -> None:
    """D-120: a manual sandbox shop visit uses the same logged-in PayPal window when the buyer is in .env."""
    c = sandbox_client
    set_buyer(c, paypal_sandbox_buyer_email="", paypal_sandbox_buyer_password="")
    assert 'data-buyer-login="1"' not in c.get("/shop/penwright").text  # no buyer: PayPal's own pop-up
    set_buyer(c, paypal_sandbox_buyer_password="s3cret-Buyer-9")
    shop = c.get("/shop/penwright").text  # a flag only: the email and password never reach the page
    assert 'data-buyer-login="1"' in shop and "personal.example" not in shop and "s3cret-Buyer-9" not in shop
    js = c.get("/shop/static/checkout_sandbox.js").text
    assert 'area.dataset.buyerLogin === "1"' in js and 'source: window.SG_AUTODEMO ? "demo" : "shop"' in js
    fake_window(c)
    res = start(c, source="shop")
    assert res.status_code == 200, res.text
    (row,) = audit(c, "demo_paypal_window")
    assert row["details"]["source"] == "shop" and row["reason"].startswith("Shop: ")


def test_static_scripts_are_revalidated(sandbox_client: TestClient) -> None:
    """A changed script must never run stale from the browser cache (D-120)."""
    for url in ("/shop/static/checkout_sandbox.js", "/static/companion.js"):
        res = sandbox_client.get(url)
        assert res.status_code == 200 and res.headers["cache-control"] == "no-cache" and res.headers["etag"]
        again = sandbox_client.get(url, headers={"If-None-Match": res.headers["etag"]})
        assert again.status_code == 304  # unchanged -> cheap revalidation

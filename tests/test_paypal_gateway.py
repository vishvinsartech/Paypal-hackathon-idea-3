"""Gateway over the mock backend: audit entries, cancel corner cases 3/4, duplicate claim, MCP fallback."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import Settings
from app.integrations.paypal_gateway import Ctx, PayPalGateway
from app.integrations.paypal_mock import MockPayPal, mock_plan_id
from app.integrations.paypal_types import PayPalError, SubscriptionView
from app.models import Subscription
from app.store import JsonStore


def mock_settings() -> Settings:
    return Settings(_env_file=None, app_mode="mock")  # type: ignore[call-arg]


@pytest.fixture
def gw(store: JsonStore) -> PayPalGateway:
    return PayPalGateway(mock_settings(), store, retry_delays=(0, 0, 0))


async def active_sub(gw: PayPalGateway, plan_key: str = "penwright-pro") -> str:
    view = await gw.create_subscription(gw.plan_id(plan_key))
    assert view.status == "APPROVAL_PENDING"
    await gw.mock_approve(view.id)
    return view.id


async def test_mock_lifecycle_and_audit(gw: PayPalGateway, store: JsonStore) -> None:
    pid = await active_sub(gw)
    out = await gw.cancel(pid, "test", Ctx(actor="user", user_id="priya"))
    assert out.ok and out.status_before == "ACTIVE" and out.status_after == "CANCELLED" and out.transport == "mock"
    calls = [e for e in store.audit.entries() if e.event == "paypal_call"]
    assert [e.details["op"] for e in calls] == [
        "create_subscription", "approve (buyer, mock)", "get_subscription", "cancel", "get_subscription"]
    assert all(e.transport == "mock" for e in calls)
    assert store.audit.verify().ok


async def test_cancel_already_cancelled_is_success(gw: PayPalGateway) -> None:
    pid = await active_sub(gw)
    assert (await gw.cancel(pid, "first")).ok
    again = await gw.cancel(pid, "second")
    assert again.ok and again.already_cancelled and again.attempts == 0


async def test_422_from_paypal_then_cancelled_counts_as_success(gw: PayPalGateway) -> None:
    """Corner case 3: PayPal answers 422 because the subscription got cancelled in the meantime."""
    pid = await active_sub(gw)
    assert gw.mock is not None
    original = gw.mock.cancel_subscription

    async def cancelled_meanwhile(sub_id: str, reason: str, **kw: object) -> None:
        await gw.mock.set_status(sub_id, "CANCELLED")  # type: ignore[union-attr]
        await original(sub_id, reason, **kw)  # type: ignore[arg-type]

    gw.mock.cancel_subscription = cancelled_meanwhile  # type: ignore[method-assign]
    out = await gw.cancel(pid, "test")
    assert out.ok and out.already_cancelled and out.status_after == "CANCELLED"


async def test_retries_reuse_the_same_request_id(gw: PayPalGateway, store: JsonStore) -> None:
    """Corner case 4: 5xx / no response -> retry with backoff and the SAME PayPal-Request-Id."""
    pid = await active_sub(gw)
    gw.mock.inject_failure("cancel", 503)  # type: ignore[union-attr]
    gw.mock.inject_failure("cancel", None)  # type: ignore[union-attr]
    out = await gw.cancel(pid, "test")
    assert out.ok and out.attempts == 3
    ids = {e.paypal_request_id for e in store.audit.entries()
           if e.event == "paypal_call" and e.details.get("op") == "cancel"}
    assert ids == {out.request_id}


async def test_401_retried_once(gw: PayPalGateway) -> None:
    pid = await active_sub(gw)
    gw.mock.inject_failure("cancel", 401)  # type: ignore[union-attr]
    out = await gw.cancel(pid, "test")
    assert out.ok and out.attempts == 2


async def test_gives_up_and_releases_claim(gw: PayPalGateway, store: JsonStore) -> None:
    pid = await active_sub(gw)
    with store.edit("subscriptions") as subs:
        subs.items.append(Subscription(id="sub-1", paypal_id=pid, plan_key="penwright-pro", plan_id="P",
                                       merchant_id="penwright", owner_id="priya", status="ACTIVE"))
    gw.mock.inject_failure("cancel", 500, times=4)  # type: ignore[union-attr]
    out = await gw.cancel(pid, "test", Ctx(subscription_id="sub-1"))
    assert not out.ok and out.attempts == 4 and out.status_after == "ACTIVE"
    sub = store.load("subscriptions").items[0]
    assert sub.cancel_requested_at is None and sub.status == "ACTIVE"  # claim released for a later attempt
    summary = [e for e in store.audit.entries() if e.event == "paypal_cancel"][-1]
    assert summary.result.startswith("failed:")
    assert (await gw.cancel(pid, "retry later", Ctx(subscription_id="sub-1"))).ok


async def test_duplicate_cancel_claim(gw: PayPalGateway, store: JsonStore) -> None:
    pid = await active_sub(gw)
    with store.edit("subscriptions") as subs:
        subs.items.append(Subscription(id="sub-1", paypal_id=pid, plan_key="penwright-pro", plan_id="P",
                                       merchant_id="penwright", owner_id="priya", status="ACTIVE"))
    first = await gw.cancel(pid, "a", Ctx(subscription_id="sub-1"))
    second = await gw.cancel(pid, "b", Ctx(subscription_id="sub-1"))
    assert first.ok and not first.already_cancelled
    assert second.ok and second.already_cancelled and second.attempts == 0
    assert store.load("subscriptions").items[0].status == "CANCELLED"


async def test_update_pricing_changes_plan(gw: PayPalGateway) -> None:
    pid = mock_plan_id("framewise-basic")
    assert (await gw.get_plan(pid)).billing_cycles[0].price == Decimal("12.00")
    await gw.update_pricing(pid, 1, Decimal("19"))
    assert (await gw.get_plan(pid)).billing_cycles[0].price == Decimal("19")


class DownMcp:
    transport = "mcp"

    async def get_subscription(self, sub_id: str, **kw: object) -> SubscriptionView:
        raise PayPalError("server not running", name="MCP_UNAVAILABLE", transport="mcp")

    async def cancel_subscription(self, sub_id: str, reason: str, **kw: object) -> None:
        raise PayPalError("server not running", name="MCP_UNAVAILABLE", transport="mcp")

    def health(self) -> dict[str, str]:
        return {"state": "unavailable", "reason": "server not running"}


async def test_mcp_down_falls_back_to_sdk_with_warning(store: JsonStore) -> None:
    """Corner case 7. The mock backend stands in for the SDK here."""
    sandbox = Settings(_env_file=None, app_mode="sandbox", paypal_client_id="c",  # type: ignore[call-arg]
                       paypal_client_secret="s", paypal_transport="mcp", paypal_merchant_mode="single")
    sdk_stand_in = MockPayPal(store)
    gw = PayPalGateway(sandbox, store, mock=None, sdk=sdk_stand_in, mcp=DownMcp(), retry_delays=(0,))
    view = await sdk_stand_in.create_subscription(mock_plan_id("lumen-monthly"), request_id="r")
    await sdk_stand_in.approve(view.id)
    out = await gw.cancel(view.id, "test")
    assert out.ok and out.status_after == "CANCELLED"
    events = [e.event for e in store.audit.entries()]
    assert events.count("paypal_mcp_fallback") >= 2  # get + cancel each fell back
    assert gw.health()["transport"] == "sdk (MCP fallback)"


def test_plan_id_requires_seed_in_sandbox(store: JsonStore) -> None:
    sandbox = Settings(_env_file=None, app_mode="sandbox", paypal_client_id="c",  # type: ignore[call-arg]
                       paypal_client_secret="s")
    gw = PayPalGateway(sandbox, store, sdk=MockPayPal(store))
    with pytest.raises(PayPalError, match="make seed"):
        gw.plan_id("penwright-pro")

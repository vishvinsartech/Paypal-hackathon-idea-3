"""SdkPayPal over paypal-server-sdk with a stubbed client (no network).

The SDK is sync, so the stub is a plain object whose controller methods return an ApiResponse-like
object (`.text`) or raise the SDK's own exception types.
"""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from typing import Any

import httpx
import pytest
import requests
import respx
from paypalserversdk.exceptions.subscription_error_exception import SubscriptionErrorException

from app.config import Settings
from app.integrations.paypal_sdk import SdkPayPal, plan_request
from app.integrations.paypal_types import PayPalError
from app.models import BillingCycleDef, Merchant, PlanDef

BASE = "https://api-m.sandbox.paypal.com"
SUB = {"id": "I-ABC123", "status": "ACTIVE", "plan_id": "P-123456789012",
       "billing_info": {"next_billing_time": "2026-11-25T10:00:00Z"},
       "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=X"}]}
PLAN = {"id": "P-123456789012", "name": "Penwright Pro", "status": "ACTIVE", "billing_cycles": [
    {"frequency": {"interval_unit": "MONTH", "interval_count": 1}, "tenure_type": "TRIAL", "sequence": 2,
     "total_cycles": 3, "pricing_scheme": {"fixed_price": {"currency_code": "USD", "value": "24.99"}}},
    {"frequency": {"interval_unit": "DAY", "interval_count": 14}, "tenure_type": "TRIAL", "sequence": 1,
     "total_cycles": 1},
    {"frequency": {"interval_unit": "MONTH", "interval_count": 1}, "tenure_type": "REGULAR", "sequence": 3,
     "total_cycles": 0, "pricing_scheme": {"fixed_price": {"currency_code": "USD", "value": "49.99"}}},
]}


class FakeHttpResponse:
    def __init__(self, status: int, body: Any = None) -> None:
        self.status_code = status
        self.text = json.dumps(body) if body is not None else ""
        self.headers: dict[str, str] = {}


def sdk_error(status: int, body: dict[str, Any]) -> SubscriptionErrorException:
    return SubscriptionErrorException("error", FakeHttpResponse(status, body))


class StubSubscriptions:
    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    def _next(self, name: str, options: dict[str, Any]) -> Any:
        self.calls.append((name, options, threading.current_thread().name))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def __getattr__(self, name: str) -> Any:
        return lambda options: self._next(name, options)


class StubClient:
    def __init__(self, subs: StubSubscriptions) -> None:
        self.subscriptions = subs


def make_sdk(*results: Any, **settings_kw: Any) -> tuple[SdkPayPal, StubSubscriptions, list[StubClient]]:
    subs = StubSubscriptions(list(results))
    built: list[StubClient] = []

    def factory() -> StubClient:
        built.append(StubClient(subs))
        return built[-1]

    s = Settings(_env_file=None, app_mode="sandbox", paypal_client_id="cid",  # type: ignore[call-arg]
                 paypal_client_secret="secret", **settings_kw)
    return SdkPayPal(s, client_factory=factory), subs, built


async def test_get_subscription_runs_in_worker_thread() -> None:
    sdk, subs, _ = make_sdk(FakeHttpResponse(200, SUB))
    view = await sdk.get_subscription("I-ABC123")
    assert view.status == "ACTIVE" and view.plan_id == "P-123456789012"
    assert view.next_billing_time == "2026-11-25T10:00:00Z"
    name, options, thread = subs.calls[0]
    assert name == "get_subscription" and options == {"id": "I-ABC123"}
    assert thread != threading.current_thread().name  # never blocks the event loop


async def test_get_plan_maps_cycles_in_sequence_order() -> None:
    sdk, subs, _ = make_sdk(FakeHttpResponse(200, PLAN))
    plan = await sdk.get_plan("P-123456789012")
    assert subs.calls[0][:2] == ("get_billing_plan", "P-123456789012")  # SDK 2.4.0: id is positional, not options
    assert [c.tenure_type for c in plan.billing_cycles] == ["TRIAL", "TRIAL", "REGULAR"]
    assert [c.price for c in plan.billing_cycles] == [Decimal("0"), Decimal("24.99"), Decimal("49.99")]
    assert plan.billing_cycles[0].interval_count == 14 and plan.billing_cycles[2].total_cycles == 0


async def test_create_subscription_passes_request_id_and_returns_approve_link() -> None:
    sdk, subs, _ = make_sdk(FakeHttpResponse(201, {**SUB, "status": "APPROVAL_PENDING"}))
    view = await sdk.create_subscription("P-123456789012", request_id="rid-c", return_url="http://r",
                                         cancel_url="http://c")
    assert view.status == "APPROVAL_PENDING" and view.approve_url and "sandbox.paypal.com" in view.approve_url
    _, options, _ = subs.calls[0]
    assert options["paypal_request_id"] == "rid-c" and options["prefer"] == "return=representation"
    assert options["body"]["plan_id"] == "P-123456789012"


async def test_401_rebuilds_client_and_retries_once() -> None:
    sdk, subs, built = make_sdk(sdk_error(401, {"name": "AUTHENTICATION_FAILURE", "message": "x", "debug_id": "d"}),
                                FakeHttpResponse(200, SUB))
    view = await sdk.get_subscription("I-ABC123")
    assert view.status == "ACTIVE" and len(built) == 2 and len(subs.calls) == 2


async def test_sdk_errors_map_to_paypal_error() -> None:
    sdk, _, _ = make_sdk(
        sdk_error(404, {"name": "RESOURCE_NOT_FOUND", "message": "Not found", "debug_id": "dbg404",
                        "details": [{"issue": "INVALID_RESOURCE_ID"}]}),
        requests.exceptions.ConnectionError("down"),
    )
    with pytest.raises(PayPalError) as e1:
        await sdk.get_subscription("I-NOPE")
    assert e1.value.status == 404 and e1.value.issues == ["INVALID_RESOURCE_ID"] and e1.value.debug_id == "dbg404"
    assert not e1.value.retryable
    with pytest.raises(PayPalError) as e2:
        await sdk.get_subscription("I-NOPE")
    assert e2.value.retryable and e2.value.name == "TRANSPORT_ERROR"


@respx.mock
async def test_cancel_goes_through_rest_with_request_id() -> None:
    sdk, subs, _ = make_sdk()
    respx.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "t"}))
    route = respx.post(f"{BASE}/v1/billing/subscriptions/I-1/cancel").mock(return_value=httpx.Response(204))
    await sdk.cancel_subscription("I-1", "SubGuard", request_id="rid-x")
    assert route.calls.last.request.headers["PayPal-Request-Id"] == "rid-x"
    assert subs.calls == []  # the SDK can't send PayPal-Request-Id on cancel


@respx.mock
async def test_partner_mode_reads_go_through_rest_with_assertion() -> None:
    sdk, subs, _ = make_sdk(paypal_merchant_mode="partner")
    respx.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "t"}))
    route = respx.get(f"{BASE}/v1/billing/subscriptions/I-ABC123").mock(return_value=httpx.Response(200, json=SUB))
    merchant = Merchant(id="penwright", name="Penwright Studio", paypal_payer_id="PAYER123")
    view = await sdk.get_subscription("I-ABC123", merchant=merchant)
    assert view.status == "ACTIVE" and "PayPal-Auth-Assertion" in route.calls.last.request.headers
    assert subs.calls == []


def test_plan_request_omits_pricing_for_free_trial() -> None:
    plan = PlanDef(key="k", name="Penwright Pro", billing_cycles=[
        BillingCycleDef(tenure_type="TRIAL", price=Decimal("0"), interval_unit="DAY", interval_count=14,
                        total_cycles=1),
        BillingCycleDef(tenure_type="REGULAR", price=Decimal("24.99"), interval_unit="MONTH", total_cycles=3)])
    body = plan_request("PROD-1", plan)
    trial, regular = body["billing_cycles"]
    assert "pricing_scheme" not in trial and trial["sequence"] == 1
    assert regular["pricing_scheme"]["fixed_price"] == {"currency_code": "USD", "value": "24.99"}


async def test_meta_reads_return_paypal_debug_ids() -> None:
    """D-113: the live verification card shows PayPal's debug id from `ApiResponse.headers`."""
    sub_resp, plan_resp = FakeHttpResponse(200, SUB), FakeHttpResponse(200, PLAN)
    sub_resp.headers = {"Paypal-Debug-Id": "dbg-sub-1"}
    plan_resp.headers = {"paypal-debug-id": "dbg-plan-2"}
    sdk, subs, _ = make_sdk(sub_resp, plan_resp)
    view, sub_debug = await sdk.get_subscription_meta("I-ABC123")
    plan, plan_debug = await sdk.get_plan_meta("P-123456789012")
    assert (view.status, sub_debug) == ("ACTIVE", "dbg-sub-1")
    assert (plan.name, plan_debug, len(plan.billing_cycles)) == ("Penwright Pro", "dbg-plan-2", 3)
    assert [c[0] for c in subs.calls] == ["get_subscription", "get_billing_plan"]


@respx.mock
async def test_cancel_returns_the_debug_id() -> None:
    sdk, _, _ = make_sdk()
    respx.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "t"}))
    respx.post(f"{BASE}/v1/billing/subscriptions/I-1/cancel").mock(
        return_value=httpx.Response(204, headers={"paypal-debug-id": "dbg-cancel"}))
    assert await sdk.cancel_subscription("I-1", "SubGuard", request_id="rid-x") == "dbg-cancel"

"""httpx gap helpers (paypal_rest.py), mocked with respx."""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.integrations.paypal_rest import PayPalRest, auth_assertion
from app.integrations.paypal_types import PayPalError
from app.models import Merchant

BASE = "https://api-m.sandbox.paypal.com"
MERCHANT = Merchant(id="penwright", name="Penwright Studio", paypal_payer_id="PAYER123")
WEBHOOK_HEADERS = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert",
                   "PAYPAL-TRANSMISSION-ID": "tid", "PAYPAL-TRANSMISSION-SIG": "sig",
                   "PAYPAL-TRANSMISSION-TIME": "2026-11-10T10:00:00Z"}


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, app_mode="sandbox", paypal_client_id="cid",  # type: ignore[call-arg]
                    paypal_client_secret="secret", **kw)


def token_route(mock: respx.MockRouter, *tokens: str) -> respx.Route:
    return mock.post(f"{BASE}/v1/oauth2/token").mock(
        side_effect=[httpx.Response(200, json={"access_token": t, "expires_in": 3600}) for t in tokens])


@pytest.fixture
def rest() -> PayPalRest:
    return PayPalRest(settings())


@respx.mock
async def test_cancel_sends_request_id_reason_and_bearer(rest: PayPalRest) -> None:
    tok = token_route(respx.mock, "tok1")
    cancel = respx.post(f"{BASE}/v1/billing/subscriptions/I-1/cancel").mock(return_value=httpx.Response(204))
    await rest.cancel_subscription("I-1", "SubGuard safety timer", request_id="rid-1")
    req = cancel.calls.last.request
    assert req.headers["PayPal-Request-Id"] == "rid-1"
    assert req.headers["Authorization"] == "Bearer tok1"
    assert "PayPal-Auth-Assertion" not in req.headers  # single merchant mode
    assert json.loads(req.content) == {"reason": "SubGuard safety timer"}
    assert tok.call_count == 1


@respx.mock
async def test_token_is_cached(rest: PayPalRest) -> None:
    tok = token_route(respx.mock, "tok1")
    respx.get(f"{BASE}/v1/billing/subscriptions/I-1").mock(return_value=httpx.Response(200, json={"id": "I-1"}))
    await rest.get_json("/v1/billing/subscriptions/I-1")
    await rest.get_json("/v1/billing/subscriptions/I-1")
    assert tok.call_count == 1


@respx.mock
async def test_401_refreshes_token_and_resends_same_request_id(rest: PayPalRest) -> None:
    token_route(respx.mock, "old", "new")
    cancel = respx.post(f"{BASE}/v1/billing/subscriptions/I-1/cancel").mock(
        side_effect=[httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"}), httpx.Response(204)])
    await rest.cancel_subscription("I-1", "x", request_id="rid-1")
    first, second = (c.request for c in cancel.calls)
    assert first.headers["Authorization"] == "Bearer old" and second.headers["Authorization"] == "Bearer new"
    assert first.headers["PayPal-Request-Id"] == second.headers["PayPal-Request-Id"] == "rid-1"


@respx.mock
async def test_422_maps_to_status_invalid(rest: PayPalRest) -> None:
    token_route(respx.mock, "t")
    respx.post(f"{BASE}/v1/billing/subscriptions/I-1/cancel").mock(return_value=httpx.Response(
        422, headers={"paypal-debug-id": "dbg"}, json={
            "name": "UNPROCESSABLE_ENTITY", "message": "The requested action could not be performed.",
            "details": [{"issue": "SUBSCRIPTION_STATUS_INVALID"}]}))
    with pytest.raises(PayPalError) as exc:
        await rest.cancel_subscription("I-1", "x", request_id="r")
    err = exc.value
    assert err.status == 422 and err.status_invalid and err.debug_id == "dbg" and not err.retryable


@respx.mock
async def test_5xx_and_network_errors_are_retryable(rest: PayPalRest) -> None:
    token_route(respx.mock, "t")
    respx.post(f"{BASE}/v1/billing/subscriptions/I-1/cancel").mock(
        side_effect=[httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"}), httpx.ConnectError("down")])
    with pytest.raises(PayPalError) as e1:
        await rest.cancel_subscription("I-1", "x", request_id="r")
    with pytest.raises(PayPalError) as e2:
        await rest.cancel_subscription("I-1", "x", request_id="r")
    assert e1.value.retryable and e1.value.status == 503
    assert e2.value.retryable and e2.value.name == "TRANSPORT_ERROR"


@respx.mock
async def test_partner_mode_adds_auth_assertion() -> None:
    rest = PayPalRest(settings(paypal_merchant_mode="partner"))
    token_route(respx.mock, "t")
    route = respx.post(f"{BASE}/v1/billing/subscriptions/I-1/cancel").mock(return_value=httpx.Response(204))
    await rest.cancel_subscription("I-1", "x", request_id="r", merchant=MERCHANT)
    header = route.calls.last.request.headers["PayPal-Auth-Assertion"]
    assert header == auth_assertion("cid", "PAYER123")
    head, payload, sig = header.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    assert json.loads(base64.urlsafe_b64decode(pad(head))) == {"alg": "none"}
    assert json.loads(base64.urlsafe_b64decode(pad(payload))) == {"iss": "cid", "payer_id": "PAYER123"}
    assert sig == ""


@respx.mock
async def test_update_pricing_body(rest: PayPalRest) -> None:
    token_route(respx.mock, "t")
    route = respx.post(f"{BASE}/v1/billing/plans/P-1/update-pricing-schemes").mock(return_value=httpx.Response(204))
    await rest.update_pricing("P-1", 1, Decimal("19"), "USD", request_id="rid-p")
    req = route.calls.last.request
    assert req.headers["PayPal-Request-Id"] == "rid-p"
    assert json.loads(req.content) == {"pricing_schemes": [{"billing_cycle_sequence": 1, "pricing_scheme": {
        "fixed_price": {"currency_code": "USD", "value": "19.00"}}}]}


@respx.mock
async def test_create_product(rest: PayPalRest) -> None:
    token_route(respx.mock, "t")
    route = respx.post(f"{BASE}/v1/catalogs/products").mock(
        return_value=httpx.Response(201, json={"id": "PROD-1", "name": "Penwright Studio"}))
    product = await rest.create_product("Penwright Studio", request_id="seed-product-penwright")
    assert product["id"] == "PROD-1"
    req = route.calls.last.request
    assert req.headers["PayPal-Request-Id"] == "seed-product-penwright"
    assert json.loads(req.content)["type"] == "SERVICE"


@respx.mock
@pytest.mark.parametrize(("status", "expected"), [("SUCCESS", True), ("FAILURE", False)])
async def test_verify_webhook_signature(rest: PayPalRest, status: str, expected: bool) -> None:
    token_route(respx.mock, "t")
    route = respx.post(f"{BASE}/v1/notifications/verify-webhook-signature").mock(
        return_value=httpx.Response(200, json={"verification_status": status}))
    event = {"id": "WH-1", "event_type": "BILLING.SUBSCRIPTION.CANCELLED"}
    assert await rest.verify_webhook_signature(WEBHOOK_HEADERS, event, "WEBHOOK-ID") is expected
    body = json.loads(route.calls.last.request.content)
    assert body["transmission_id"] == "tid" and body["webhook_id"] == "WEBHOOK-ID" and body["webhook_event"] == event
    assert body["auth_algo"] == "SHA256withRSA" and body["cert_url"].startswith("https://")


async def test_verify_webhook_rejects_missing_headers_without_calling_paypal(rest: PayPalRest) -> None:
    partial = {k: v for k, v in WEBHOOK_HEADERS.items() if k != "PAYPAL-TRANSMISSION-SIG"}
    assert await rest.verify_webhook_signature(partial, {"id": "WH-1"}, "WEBHOOK-ID") is False
    assert await rest.verify_webhook_signature(WEBHOOK_HEADERS, {"id": "WH-1"}, "") is False

"""PayPal sandbox via the official `paypal-server-sdk` 2.4.0 (import `paypalserversdk`).

The SDK is synchronous (requests-based), so every call runs in a worker thread (`asyncio.to_thread`) to
keep the FastAPI event loop free. Contract facts: docs/PAYPAL_SDK_NOTES.md. What the SDK can't do
(PayPal-Request-Id on cancel/update-pricing, PayPal-Auth-Assertion, products, webhook verification) goes
through `PayPalRest` (httpx). In partner mode every merchant-side call goes through REST, because only
REST can carry the assertion header.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from paypalserversdk.configuration import Environment
from paypalserversdk.controllers.subscriptions_controller import SubscriptionsController
from paypalserversdk.exceptions.api_exception import ApiException
from paypalserversdk.exceptions.o_auth_provider_exception import OAuthProviderException
from paypalserversdk.exceptions.subscription_error_exception import SubscriptionErrorException
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

from app.config import Settings
from app.integrations.paypal_rest import RETRYABLE_STATUSES, PayPalRest
from app.integrations.paypal_types import PayPalError, PlanView, SubscriptionView, plan_view, subscription_view
from app.models import Merchant, PlanDef

SdkCall = Callable[[SubscriptionsController], Any]


def to_paypal_error(exc: Exception) -> PayPalError:
    """Map every SDK failure to PayPalError: typed API errors, OAuth failures, HTTP errors, network errors."""
    if isinstance(exc, SubscriptionErrorException):
        issues = [d.issue for d in (getattr(exc, "details", None) or []) if getattr(d, "issue", None)]
        return PayPalError(getattr(exc, "message", None) or exc.reason, status=exc.response_code,
                           name=getattr(exc, "name", None), debug_id=getattr(exc, "debug_id", None), issues=issues,
                           retryable=exc.response_code in RETRYABLE_STATUSES)
    if isinstance(exc, OAuthProviderException):
        return PayPalError(f"PayPal OAuth failed: {exc.error_description or exc.error}", status=exc.response_code,
                           name=f"OAUTH_{exc.error}".upper())
    if isinstance(exc, ApiException):
        debug_id = (getattr(exc.response, "headers", None) or {}).get("paypal-debug-id")
        return PayPalError(exc.reason or f"HTTP {exc.response_code}", status=exc.response_code, name="HTTP_ERROR",
                           debug_id=debug_id, retryable=exc.response_code in RETRYABLE_STATUSES)
    if type(exc).__module__.split(".")[0] in ("requests", "urllib3"):
        return PayPalError(f"no response from PayPal: {type(exc).__name__}", name="TRANSPORT_ERROR", retryable=True)
    raise exc


def plan_request(product_id: str, plan: PlanDef) -> dict[str, Any]:
    cycles = []
    for seq, c in enumerate(plan.billing_cycles, start=1):
        cycle: dict[str, Any] = {
            "frequency": {"interval_unit": c.interval_unit, "interval_count": c.interval_count},
            "tenure_type": c.tenure_type, "sequence": seq, "total_cycles": c.total_cycles,
        }
        if not (c.tenure_type == "TRIAL" and c.price == 0):  # a free trial has no pricing scheme
            cycle["pricing_scheme"] = {"fixed_price": {"currency_code": plan.currency, "value": f"{c.price:.2f}"}}
        cycles.append(cycle)
    return {"product_id": product_id, "name": plan.name, "billing_cycles": cycles,
            "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 1}}


class SdkPayPal:
    transport = "sdk"

    def __init__(self, settings: Settings, *, rest: PayPalRest | None = None,
                 client_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self.rest = rest or PayPalRest(settings)
        self._client_factory = client_factory or self._new_client
        self.client = self._client_factory()

    def _new_client(self) -> PaypalServersdkClient:
        return PaypalServersdkClient(
            client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                o_auth_client_id=self.settings.paypal_client_id,
                o_auth_client_secret=self.settings.paypal_client_secret),
            environment=Environment.SANDBOX,  # sandbox only; startup refuses any other PAYPAL_API_BASE
            timeout=30, max_retries=2,  # the SDK retries GET/PUT only, never our POSTs
        )

    async def aclose(self) -> None:
        await self.rest.aclose()

    def _partner(self, merchant: Merchant | None) -> bool:
        return self.settings.paypal_merchant_mode == "partner" and bool(merchant and merchant.paypal_payer_id)

    async def _sdk(self, call: SdkCall) -> dict[str, Any]:
        """Run one SDK call in a thread. On 401, rebuild the client (fresh token) and retry once."""
        for attempt in (1, 2):
            client = self.client
            try:
                resp = await asyncio.to_thread(call, client.subscriptions)
            except Exception as exc:  # noqa: BLE001 - mapped (or re-raised) right here
                err = to_paypal_error(exc)
                if err.status == 401 and attempt == 1:
                    self.client = self._client_factory()
                    continue
                raise err from exc
            return json.loads(resp.text) if resp.text else {}
        raise AssertionError("unreachable")

    async def get_subscription(self, sub_id: str, *, merchant: Merchant | None = None) -> SubscriptionView:
        if self._partner(merchant):
            return subscription_view(await self.rest.get_json(f"/v1/billing/subscriptions/{sub_id}", merchant=merchant))
        return subscription_view(await self._sdk(lambda s: s.get_subscription({"id": sub_id})), sub_id)

    async def get_plan(self, plan_id: str, *, merchant: Merchant | None = None) -> PlanView:
        if self._partner(merchant):
            return plan_view(await self.rest.get_json(f"/v1/billing/plans/{plan_id}", merchant=merchant))
        return plan_view(await self._sdk(lambda s: s.get_billing_plan({"id": plan_id})))

    async def cancel_subscription(self, sub_id: str, reason: str, *, request_id: str,
                                  merchant: Merchant | None = None) -> None:
        await self.rest.cancel_subscription(sub_id, reason, request_id=request_id, merchant=merchant)

    async def update_pricing(self, plan_id: str, sequence: int, price: Decimal, currency: str, *,
                             request_id: str, merchant: Merchant | None = None) -> None:
        await self.rest.update_pricing(plan_id, sequence, price, currency, request_id=request_id, merchant=merchant)

    async def create_subscription(self, plan_id: str, *, request_id: str, return_url: str | None = None,
                                  cancel_url: str | None = None,
                                  merchant: Merchant | None = None) -> SubscriptionView:
        body: dict[str, Any] = {"plan_id": plan_id}
        if return_url and cancel_url:
            body["application_context"] = {"return_url": return_url, "cancel_url": cancel_url,
                                           "user_action": "SUBSCRIBE_NOW", "brand_name": "SubGuard demo"}
        if self._partner(merchant):
            resp = await self.rest.request("POST", "/v1/billing/subscriptions", json_body=body,
                                           request_id=request_id, merchant=merchant)
            return subscription_view(resp.json())
        data = await self._sdk(lambda s: s.create_subscription(
            {"body": body, "paypal_request_id": request_id, "prefer": "return=representation"}))
        return subscription_view(data)

    async def create_plan(self, product_id: str, plan: PlanDef, *, request_id: str) -> PlanView:
        data = await self._sdk(lambda s: s.create_billing_plan(
            {"body": plan_request(product_id, plan), "paypal_request_id": request_id,
             "prefer": "return=representation"}))
        return plan_view(data)

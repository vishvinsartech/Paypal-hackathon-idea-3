"""Small httpx helpers for what paypal-server-sdk 2.4.0 can't do (DECISIONS D-010):

- `PayPal-Request-Id` on cancel / update-pricing (the SDK only exposes it on create calls)
- `PayPal-Auth-Assertion` for partner mode (the SDK has no per-call custom headers)
- Catalog Products (no controller in the SDK); webhook signature verification (not in the SDK)
- a raw access token for the PayPal MCP server

Sandbox only: the base URL comes from settings, which refuse anything but the sandbox at startup.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings
from app.integrations.paypal_types import PayPalError
from app.models import Merchant

RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
WEBHOOK_HEADERS = {
    "auth_algo": "paypal-auth-algo", "cert_url": "paypal-cert-url", "transmission_id": "paypal-transmission-id",
    "transmission_sig": "paypal-transmission-sig", "transmission_time": "paypal-transmission-time",
}


def auth_assertion(client_id: str, payer_id: str) -> str:
    """Unsigned JWT (alg none) naming the merchant we act for (partner mode, experimental)."""
    def b64(obj: dict[str, str]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64({'iss': client_id, 'payer_id': payer_id})}."


def error_from_response(resp: httpx.Response) -> PayPalError:
    debug_id = resp.headers.get("paypal-debug-id")
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    issues = [d.get("issue", "") for d in body.get("details") or [] if isinstance(d, dict)]
    return PayPalError(
        body.get("message") or body.get("error_description") or f"HTTP {resp.status_code}",
        status=resp.status_code, name=body.get("name") or body.get("error") or "HTTP_ERROR",
        debug_id=body.get("debug_id") or debug_id, issues=issues,
        retryable=resp.status_code in RETRYABLE_STATUSES, transport="rest",
    )


class PayPalRest:
    def __init__(self, settings: Settings, *, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.base = settings.paypal_api_base.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=30)
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self.http.aclose()

    async def token(self, *, force: bool = False) -> str:
        """Client-credentials token, cached until 60s before expiry."""
        async with self._lock:
            if self._token and not force and time.monotonic() < self._expires_at:
                return self._token
            try:
                resp = await self.http.post(f"{self.base}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                                            auth=(self.settings.paypal_client_id, self.settings.paypal_client_secret))
            except httpx.TransportError as exc:
                raise PayPalError(f"no response from PayPal: {type(exc).__name__}", name="TRANSPORT_ERROR",
                                  retryable=True, transport="rest") from exc
            if resp.status_code != 200:
                raise error_from_response(resp)
            data = resp.json()
            self._token = str(data["access_token"])
            self._expires_at = time.monotonic() + max(int(data.get("expires_in", 300)) - 60, 30)
            return self._token

    def headers(self, *, request_id: str | None = None, merchant: Merchant | None = None) -> dict[str, str]:
        h: dict[str, str] = {}
        if request_id:
            h["PayPal-Request-Id"] = request_id
        if self.settings.paypal_merchant_mode == "partner" and merchant and merchant.paypal_payer_id:
            h["PayPal-Auth-Assertion"] = auth_assertion(self.settings.paypal_client_id, merchant.paypal_payer_id)
        return h

    async def request(self, method: str, path: str, *, json_body: Any = None, request_id: str | None = None,
                      merchant: Merchant | None = None) -> httpx.Response:
        """Send with a bearer token; on 401 refresh the token and resend once (same PayPal-Request-Id)."""
        extra = self.headers(request_id=request_id, merchant=merchant)
        for attempt in (1, 2):
            token = await self.token(force=attempt == 2)
            try:
                resp = await self.http.request(method, f"{self.base}{path}", json=json_body,
                                               headers={"Authorization": f"Bearer {token}", **extra})
            except httpx.TransportError as exc:
                raise PayPalError(f"no response from PayPal: {type(exc).__name__}", name="TRANSPORT_ERROR",
                                  retryable=True, transport="rest") from exc
            if resp.status_code == 401 and attempt == 1:
                continue
            if resp.status_code >= 400:
                raise error_from_response(resp)
            return resp
        raise AssertionError("unreachable")

    async def get_json(self, path: str, *, merchant: Merchant | None = None) -> dict[str, Any]:
        return (await self.request("GET", path, merchant=merchant)).json()

    async def get_json_meta(self, path: str, *, merchant: Merchant | None = None) -> tuple[dict[str, Any], str | None]:
        resp = await self.request("GET", path, merchant=merchant)
        return resp.json(), resp.headers.get("paypal-debug-id")

    async def cancel_subscription(self, sub_id: str, reason: str, *, request_id: str,
                                  merchant: Merchant | None = None) -> str | None:
        resp = await self.request("POST", f"/v1/billing/subscriptions/{sub_id}/cancel",
                                  json_body={"reason": reason[:128]}, request_id=request_id, merchant=merchant)
        return resp.headers.get("paypal-debug-id")

    async def update_pricing(self, plan_id: str, sequence: int, price: Decimal, currency: str, *,
                             request_id: str, merchant: Merchant | None = None) -> None:
        body = {"pricing_schemes": [{"billing_cycle_sequence": sequence, "pricing_scheme": {
            "fixed_price": {"currency_code": currency, "value": f"{price:.2f}"}}}]}
        await self.request("POST", f"/v1/billing/plans/{plan_id}/update-pricing-schemes", json_body=body,
                           request_id=request_id, merchant=merchant)

    async def create_product(self, name: str, *, request_id: str, description: str = "",
                             product_type: str = "SERVICE") -> dict[str, Any]:
        body = {"name": name, "type": product_type, "category": "SOFTWARE",
                **({"description": description} if description else {})}
        return (await self.request("POST", "/v1/catalogs/products", json_body=body, request_id=request_id)).json()

    async def verify_webhook_signature(self, headers: Mapping[str, str], event: dict[str, Any],
                                       webhook_id: str) -> bool:
        """True only if PayPal answers verification_status == SUCCESS. Missing headers -> False."""
        lower = {k.lower(): v for k, v in headers.items()}
        fields = {key: lower.get(header) for key, header in WEBHOOK_HEADERS.items()}
        if not webhook_id or not all(fields.values()):
            return False
        body = {**fields, "webhook_id": webhook_id, "webhook_event": event}
        resp = await self.request("POST", "/v1/notifications/verify-webhook-signature", json_body=body)
        return resp.json().get("verification_status") == "SUCCESS"

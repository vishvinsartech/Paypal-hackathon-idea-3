"""The PayPal facade everyone uses (spec 7.1).

Routing: mock mode -> mock. Sandbox: get/cancel go via MCP when PAYPAL_TRANSPORT=mcp and merchant mode is
`single` (falling back to the SDK with a logged warning), otherwise via the SDK. update_pricing and plan
reads always use the SDK. Every call writes an audit log entry.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import Settings
from app.integrations.paypal_mock import MockPayPal, mock_plan_id
from app.integrations.paypal_types import FullBackend, PayPalBackend, PayPalError, PlanView, SubscriptionView
from app.models import Merchant
from app.store import JsonStore, utcnow

T = TypeVar("T")
FALLBACK_ERRORS = {"MCP_UNAVAILABLE", "MCP_TOOL_ERROR"}


@dataclass
class Ctx:
    """Who/why for the audit log."""

    actor: str = "system"
    user_id: str | None = None
    subscription_id: str | None = None  # SubGuard's local id
    merchant: Merchant | None = None
    rule_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Verified(BaseModel):
    subscription: SubscriptionView
    plan: PlanView
    transport: str
    subscription_debug_id: str | None = None
    plan_debug_id: str | None = None
    checked_at: datetime


class CancelOutcome(BaseModel):
    ok: bool
    paypal_id: str
    status_before: str | None = None
    status_after: str | None = None
    already_cancelled: bool = False
    transport: str
    request_id: str
    attempts: int = 0
    error: str | None = None
    debug_id: str | None = None


READ_OPS = {"get_subscription", "verify_subscription", "verify_plan", "get_plan"}


class PayPalGateway:
    def __init__(self, settings: Settings, store: JsonStore, *, mock: MockPayPal | None = None,
                 sdk: FullBackend | None = None, mcp: PayPalBackend | None = None,
                 retry_delays: Sequence[float] = (0.5, 1.0, 2.0)) -> None:
        self.settings = settings
        self.store = store
        self.mock = mock if mock is not None else (MockPayPal(store) if not settings.is_sandbox else None)
        self.sdk = sdk
        self.mcp = mcp
        self.retry_delays = list(retry_delays)

    # ---- routing ------------------------------------------------------------
    @property
    def full(self) -> FullBackend:
        backend = self.mock if self.mock is not None else self.sdk
        if backend is None:
            raise PayPalError("PayPal SDK backend not configured", name="NOT_CONFIGURED")
        return backend

    def _use_mcp(self) -> bool:
        return (self.mock is None and self.mcp is not None and self.settings.paypal_transport == "mcp"
                and self.settings.paypal_merchant_mode == "single")

    def health(self) -> dict[str, Any]:
        if self.mock is not None:
            return {"state": "mock", "transport": "mock"}
        info: dict[str, Any] = {"state": "sandbox", "merchant_mode": self.settings.paypal_merchant_mode,
                                "transport": self.settings.paypal_transport}
        if self._use_mcp():
            mcp_health = getattr(self.mcp, "health", lambda: {"state": "unknown"})()
            info["mcp"] = mcp_health
            if mcp_health.get("state") != "connected":
                info["transport"] = "sdk (MCP fallback)"
        return info

    def plan_id(self, plan_key: str) -> str:
        if self.mock is not None:
            return mock_plan_id(plan_key)
        pid = self.store.load("sandbox_ids").plans.get(plan_key)
        if not pid:
            raise PayPalError(f"No sandbox plan for {plan_key!r}. Run `make seed` first.", name="NOT_SEEDED")
        return pid

    # ---- audited call helpers ----------------------------------------------
    def _audit(self, op: str, ctx: Ctx, *, transport: str, result: str, request_id: str | None = None,
               debug_id: str | None = None, before: str | None = None, after: str | None = None,
               **details: Any) -> None:
        # U26: successful reads (the poller, live status re-reads, plan fetches) are routine: still hash-chained,
        # hidden by default in the grids and summaries. Writes and errors are never routine.
        tag = {"routine": True} if op in READ_OPS and result == "ok" else {}
        self.store.audit.append(
            actor=ctx.actor, event="paypal_call", user_id=ctx.user_id, subscription_id=ctx.subscription_id,  # type: ignore[arg-type]
            rule_id=ctx.rule_id, transport=transport, paypal_request_id=request_id, paypal_debug_id=debug_id,
            status_before=before, status_after=after, result=result,
            details={"op": op, **ctx.extra, **details, **tag},
        )

    async def _call(self, op: str, ctx: Ctx, backend: PayPalBackend, fn: Callable[[], Awaitable[T]], *,
                    request_id: str | None = None, **details: Any) -> T:
        try:
            value = await fn()
        except PayPalError as exc:
            self._audit(op, ctx, transport=backend.transport, result=f"error:{exc.summary()}",
                        request_id=request_id, debug_id=exc.debug_id, **details)
            raise
        head: Any = value
        debug = None
        if isinstance(value, tuple) and len(value) == 2:  # (view, paypal-debug-id) from the *_meta reads
            head, debug = value
        elif isinstance(value, str):  # cancel returns PayPal's debug id
            debug = value
        after = head.status if isinstance(head, SubscriptionView) else None
        self._audit(op, ctx, transport=backend.transport, result="ok", request_id=request_id, debug_id=debug,
                    after=after, **details)
        return value

    async def _routed(self, op: str, ctx: Ctx, run: Callable[[PayPalBackend], Awaitable[T]], *,
                      request_id: str | None = None, **details: Any) -> T:
        """Run via MCP when configured, else the full backend; MCP trouble -> SDK with a logged warning."""
        if self._use_mcp():
            assert self.mcp is not None
            mcp = self.mcp
            try:
                return await self._call(op, ctx, mcp, lambda: run(mcp), request_id=request_id, **details)
            except PayPalError as exc:
                if exc.name not in FALLBACK_ERRORS:
                    raise
                self.store.audit.append(actor="system", event="paypal_mcp_fallback", user_id=ctx.user_id,
                                        subscription_id=ctx.subscription_id, transport="sdk",
                                        reason=f"MCP {op} failed, using SDK: {exc.message[:160]}")
        full = self.full
        return await self._call(op, ctx, full, lambda: run(full), request_id=request_id, **details)

    # ---- public API ---------------------------------------------------------
    async def get_subscription(self, paypal_id: str, ctx: Ctx | None = None) -> SubscriptionView:
        ctx = ctx or Ctx()
        return await self._routed("get_subscription", ctx,
                                  lambda b: b.get_subscription(paypal_id, merchant=ctx.merchant),
                                  paypal_id=paypal_id)

    async def verify(self, paypal_id: str, ctx: Ctx | None = None) -> Verified:
        """Live read of the subscription and its plan, straight from PayPal (never from our JSON files), with
        PayPal's debug ids. Uses the full backend (SDK in sandbox) because MCP results carry no headers (D-113)."""
        ctx = ctx or Ctx()
        full = self.full
        sub, sub_debug = await self._call("verify_subscription", ctx, full, lambda: full.get_subscription_meta(
            paypal_id, merchant=ctx.merchant), paypal_id=paypal_id)
        plan, plan_debug = await self._call("verify_plan", ctx, full, lambda: full.get_plan_meta(
            sub.plan_id or "", merchant=ctx.merchant), plan_id=sub.plan_id)
        return Verified(subscription=sub, plan=plan, transport=full.transport, subscription_debug_id=sub_debug,
                        plan_debug_id=plan_debug, checked_at=utcnow())

    async def get_plan(self, plan_id: str, ctx: Ctx | None = None) -> PlanView:
        ctx = ctx or Ctx()
        full = self.full
        return await self._call("get_plan", ctx, full, lambda: full.get_plan(plan_id, merchant=ctx.merchant),
                                plan_id=plan_id)

    async def create_subscription(self, plan_id: str, ctx: Ctx | None = None, *, return_url: str | None = None,
                                  cancel_url: str | None = None, request_id: str | None = None) -> SubscriptionView:
        ctx = ctx or Ctx()
        rid = request_id or f"subguard-create-{uuid.uuid4()}"
        full = self.full
        view = await self._call(
            "create_subscription", ctx, full,
            lambda: full.create_subscription(plan_id, request_id=rid, return_url=return_url, cancel_url=cancel_url,
                                             merchant=ctx.merchant),
            request_id=rid, plan_id=plan_id)
        # Links our PayPal-Request-Id to the subscription id PayPal returned (the card shows it, D-113).
        self.store.audit.append(actor=ctx.actor, event="paypal_subscription_created", user_id=ctx.user_id,  # type: ignore[arg-type]
                                transport=full.transport, paypal_request_id=rid,  # type: ignore[arg-type]
                                status_after=view.status, result="ok",
                                details={"paypal_id": view.id, "plan_id": plan_id})
        return view

    async def update_pricing(self, plan_id: str, sequence: int, price: Decimal, currency: str = "USD",
                             ctx: Ctx | None = None) -> None:
        ctx = ctx or Ctx()
        rid = f"subguard-pricing-{uuid.uuid4()}"
        full = self.full
        await self._call("update_pricing", ctx, full,
                         lambda: full.update_pricing(plan_id, sequence, price, currency, request_id=rid,
                                                     merchant=ctx.merchant),
                         request_id=rid, plan_id=plan_id, sequence=sequence, price=f"{price:.2f}", currency=currency)

    async def mock_approve(self, paypal_id: str, ctx: Ctx | None = None) -> SubscriptionView:
        if self.mock is None:
            raise PayPalError("mock approval is only available in mock mode", name="NOT_MOCK")
        ctx = ctx or Ctx()
        mock = self.mock
        return await self._call("approve (buyer, mock)", ctx, mock, lambda: mock.approve(paypal_id),
                                paypal_id=paypal_id)

    async def _status(self, paypal_id: str, ctx: Ctx) -> str | None:
        try:
            return (await self.get_subscription(paypal_id, ctx)).status
        except PayPalError:
            return None

    async def cancel(self, paypal_id: str, reason: str, ctx: Ctx | None = None) -> CancelOutcome:
        """Cancel with claim -> call -> record. Same PayPal-Request-Id on every retry (corner case 4);
        422 + now CANCELLED counts as success (corner case 3); 401 retried once after token invalidation."""
        ctx = ctx or Ctx()
        rid = f"subguard-cancel-{paypal_id}-{uuid.uuid4().hex[:8]}"
        transport = "mcp" if self._use_mcp() else self.full.transport
        claimed = await self._claim_cancel(ctx)
        if claimed is not None:
            return CancelOutcome(ok=claimed, paypal_id=paypal_id, transport=transport, request_id=rid,
                                 already_cancelled=claimed, status_after="CANCELLED" if claimed else None,
                                 error=None if claimed else "a cancel for this subscription is already in progress")
        before = await self._status(paypal_id, ctx)
        out = CancelOutcome(ok=False, paypal_id=paypal_id, status_before=before, transport=transport, request_id=rid)
        if before == "CANCELLED":
            out.ok = out.already_cancelled = True
        else:
            out = await self._cancel_with_retries(paypal_id, reason, ctx, out)
        out.status_after = "CANCELLED" if out.already_cancelled else await self._status(paypal_id, ctx)
        if out.ok and out.status_after not in (None, "CANCELLED"):
            out.ok, out.error = False, f"PayPal still shows {out.status_after} after cancel"
        await self._record_cancel(ctx, out)
        return out

    async def _cancel_with_retries(self, paypal_id: str, reason: str, ctx: Ctx, out: CancelOutcome) -> CancelOutcome:
        delays, retried_401 = list(self.retry_delays), False
        while True:
            out.attempts += 1
            try:
                out.debug_id = await self._routed("cancel", ctx, lambda b: b.cancel_subscription(
                    paypal_id, reason, request_id=out.request_id, merchant=ctx.merchant),
                    request_id=out.request_id, paypal_id=paypal_id, attempt=out.attempts)
                out.ok, out.error = True, None
                return out
            except PayPalError as exc:
                out.error, out.debug_id = exc.summary(), exc.debug_id
                if exc.status_invalid:
                    if await self._status(paypal_id, ctx) == "CANCELLED":
                        out.ok, out.already_cancelled = True, True
                    return out
                if exc.status == 401 and not retried_401:
                    retried_401 = True  # the SDK invalidated its cached token; the next call re-authenticates
                    continue
                if exc.retryable and delays:
                    await asyncio.sleep(delays.pop(0))
                    continue
                return out

    async def _claim_cancel(self, ctx: Ctx) -> bool | None:
        """None = claimed (go ahead). True = already cancelled. False = another cancel is in flight."""
        if not ctx.subscription_id:
            return None
        async with self.store.aedit("subscriptions") as subs:
            sub = next((s for s in subs.items if s.id == ctx.subscription_id), None)
            if sub is None:
                return None
            if sub.status == "CANCELLED":
                return True
            if sub.cancel_requested_at is not None:
                return False
            sub.cancel_requested_at = utcnow()
            return None

    async def _record_cancel(self, ctx: Ctx, out: CancelOutcome) -> None:
        if ctx.subscription_id:
            async with self.store.aedit("subscriptions") as subs:
                sub = next((s for s in subs.items if s.id == ctx.subscription_id), None)
                if sub is not None:
                    if out.status_after:
                        sub.status = out.status_after  # type: ignore[assignment]
                    if out.ok:
                        sub.cancelled_at = sub.cancelled_at or utcnow()
                    else:
                        sub.cancel_requested_at = None  # release the claim so a later attempt can run
        self.store.audit.append(
            actor=ctx.actor, event="paypal_cancel", user_id=ctx.user_id, subscription_id=ctx.subscription_id,  # type: ignore[arg-type]
            rule_id=ctx.rule_id, transport=out.transport, paypal_request_id=out.request_id,  # type: ignore[arg-type]
            paypal_debug_id=out.debug_id, status_before=out.status_before, status_after=out.status_after,
            result="ok" if out.ok else f"failed:{out.error}", reason=ctx.extra.get("reason"),
            details={"paypal_id": out.paypal_id, "attempts": out.attempts,
                     "already_cancelled": out.already_cancelled},
        )

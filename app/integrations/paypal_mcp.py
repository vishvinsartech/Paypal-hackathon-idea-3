"""PayPal MCP server (`npx -y @paypal/mcp --tools=all`) through the Python `mcp` SDK.

One long-lived stdio session, started in the FastAPI lifespan (sandbox mode only). It runs in its own
task, because the stdio client's cancel scopes must be entered and exited in the same task. Used for reading
and cancelling subscriptions in single-merchant mode. Any failure raises PayPalError(name="MCP_UNAVAILABLE"),
and the gateway then falls back to the SDK (corner case 7). Tool names: docs/PAYPAL_TOOLS.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.integrations.paypal_types import PayPalError, SubscriptionView, subscription_view
from app.models import Merchant

log = logging.getLogger("subguard.paypal_mcp")
REQUIRED_TOOLS = ("show_subscription_details", "cancel_subscription")
START_TIMEOUT = 90.0
CALL_TIMEOUT = 45.0
RESTART_COOLDOWN = 60.0


class McpPayPal:
    transport = "mcp"

    def __init__(self, token_provider: Callable[[], Awaitable[str]], *, command: list[str] | None = None) -> None:
        self.token_provider = token_provider
        self.command = command or [shutil.which("npx") or "npx", "-y", "@paypal/mcp", "--tools=all"]
        self.session: ClientSession | None = None
        self.tools: set[str] = set()
        self.server_version: str | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._failed_at: float | None = None

    @property
    def available(self) -> bool:
        return self.session is not None and all(t in self.tools for t in REQUIRED_TOOLS)

    def health(self) -> dict[str, str]:
        if self.available:
            return {"state": "connected", "server": self.server_version or "?"}
        return {"state": "unavailable", "reason": self.last_error or "not started"}

    # ---- lifecycle ----------------------------------------------------------
    async def start(self) -> bool:
        async with self._lock:
            return await self._start_locked()

    async def _start_locked(self) -> bool:
        await self._stop_locked()
        try:
            token = await self.token_provider()
        except Exception as exc:  # noqa: BLE001 - report, don't crash startup
            self.last_error = f"token fetch failed: {type(exc).__name__}"
            return False
        ready = asyncio.Event()
        self._stop = asyncio.Event()
        params = StdioServerParameters(
            command=self.command[0], args=self.command[1:],
            env={**os.environ, "PAYPAL_ACCESS_TOKEN": token, "PAYPAL_ENVIRONMENT": "SANDBOX"},
        )

        async def runner() -> None:
            try:
                async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                    info = await session.initialize()
                    self.server_version = f"{info.server_info.name} {info.server_info.version}"
                    self.tools = {t.name for t in (await session.list_tools()).tools}
                    missing = [t for t in REQUIRED_TOOLS if t not in self.tools]
                    if missing:
                        self.last_error = f"tools missing: {', '.join(missing)}"
                        log.warning(self.last_error)
                    self.session = session
                    ready.set()
                    await self._stop.wait()
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"MCP server failed: {type(exc).__name__}: {exc}"[:200]
                log.warning(self.last_error)
            finally:
                self.session = None
                ready.set()

        self._task = asyncio.create_task(runner(), name="paypal-mcp")
        try:
            await asyncio.wait_for(ready.wait(), START_TIMEOUT)
        except TimeoutError:
            self.last_error = "MCP server did not start in time"
        if self.available:
            self.last_error = None
        return self.available

    async def connect(self) -> bool:
        """Don't hammer a broken server: after a failed start, wait RESTART_COOLDOWN before trying again."""
        loop = asyncio.get_running_loop()
        if self._failed_at is not None and loop.time() - self._failed_at < RESTART_COOLDOWN:
            return False
        ok = await self.start()
        self._failed_at = None if ok else loop.time()
        return ok

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, 10)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        self.session = None

    # ---- calls --------------------------------------------------------------
    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        """Call a tool. Reconnects once (fresh token) on a dead session. Tool errors -> MCP_TOOL_ERROR."""
        for _attempt in (1, 2):
            if not self.available and not await self.connect():
                raise PayPalError(self.last_error or "PayPal MCP unavailable", name="MCP_UNAVAILABLE",
                                  transport="mcp")
            assert self.session is not None
            try:
                result = await asyncio.wait_for(self.session.call_tool(tool, args), CALL_TIMEOUT)
            except Exception as exc:  # noqa: BLE001 - session died or timed out
                self.last_error = f"call failed: {type(exc).__name__}"
                await self.stop()
                continue
            text = "\n".join(getattr(c, "text", "") for c in (getattr(result, "content", None) or []))
            if getattr(result, "is_error", False):
                raise PayPalError(f"MCP tool {tool} error: {text[:300]}", name="MCP_TOOL_ERROR", transport="mcp",
                                  issues=[i for i in ("SUBSCRIPTION_STATUS_INVALID",) if i in text])
            structured = getattr(result, "structured_content", None)
            if structured:
                return structured
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}
        raise PayPalError(self.last_error or "PayPal MCP unavailable", name="MCP_UNAVAILABLE", transport="mcp")

    async def get_subscription(self, sub_id: str, *, merchant: Merchant | None = None) -> SubscriptionView:
        data = await self.call("show_subscription_details", {"subscription_id": sub_id})
        if not isinstance(data, dict) or "status" not in data:
            raise PayPalError("unexpected MCP response for show_subscription_details", name="MCP_TOOL_ERROR",
                              transport="mcp")
        return subscription_view(data, sub_id)

    async def cancel_subscription(self, sub_id: str, reason: str, *, request_id: str,
                                  merchant: Merchant | None = None) -> str | None:
        await self.call("cancel_subscription", {"subscription_id": sub_id, "payload": {"reason": reason[:128]}})
        return None  # the MCP tool result carries no PayPal headers

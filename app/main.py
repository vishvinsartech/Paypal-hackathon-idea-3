"""FastAPI entry point: `uvicorn app.main:app --host 127.0.0.1 --port 8000` (1 worker)."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR, ConfigError, Settings, load_settings
from app.core.audit_log import mask_secrets
from app.core.auditor import Auditor
from app.integrations.capture import Capturer, PlaywrightCapture, StaticCapture
from app.integrations.paypal_gateway import PayPalGateway
from app.integrations.paypal_mcp import McpPayPal
from app.integrations.paypal_rest import PayPalRest
from app.integrations.paypal_sdk import SdkPayPal
from app.integrations.paypal_types import PayPalError
from app.llm import build_llm
from app.routes import api, demo, pages, review, subscriptions
from app.routes.subscriptions import paypal_error_response
from app.store import JsonStore
from shop import routes as shop_routes


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        return json.dumps(mask_secrets(payload))


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("subguard")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False


def create_app(settings: Settings | None = None) -> FastAPI:
    setup_logging()
    log = logging.getLogger("subguard")
    if settings is None:
        try:
            settings = load_settings()
        except ConfigError as exc:
            log.error(str(exc))
            raise SystemExit(str(exc)) from None

    store = JsonStore(settings.runtime_dir, settings.seed_dir, app_mode=settings.app_mode, pricing=settings.pricing)
    gateway = build_gateway(settings, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        mcp_task = None
        if isinstance(gateway.mcp, McpPayPal):  # connect in the background so startup isn't blocked by npx
            mcp_task = asyncio.create_task(gateway.mcp.connect(), name="paypal-mcp-connect")
        store.ensure_all()
        store.check_pricing()
        async with store.aedit("state") as state:
            state.app_mode = settings.app_mode
        store.audit.append(
            actor="system", event="startup", reason=f"SubGuard started in {settings.app_mode} mode",
            details={"mode": settings.app_mode, "llm_provider": settings.active_llm_provider,
                     "llm_model": settings.llm_model},
        )
        log.info(f"SubGuard running in {settings.app_mode} mode at http://{settings.app_host}:{settings.app_port}/")
        yield
        if mcp_task is not None:
            mcp_task.cancel()
        if isinstance(gateway.mcp, McpPayPal):
            await gateway.mcp.stop()
        if isinstance(gateway.sdk, SdkPayPal):
            await gateway.sdk.aclose()

    app = FastAPI(title="SubGuard", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.gateway = gateway
    app.state.llm = build_llm(settings)
    app.state.capture = build_capture(settings, app)
    app.state.auditor = Auditor(app.state.llm, store, settings.seed_dir / "dark_patterns.json",
                                settings.llm_timeout_seconds)

    @app.exception_handler(PayPalError)
    async def _paypal_error(_request: Request, exc: PayPalError) -> JSONResponse:
        return paypal_error_response(exc)

    app.mount("/static", StaticFiles(directory=ROOT_DIR / "app" / "static"), name="static")
    app.mount("/shop/static", StaticFiles(directory=ROOT_DIR / "shop" / "static"), name="shop_static")
    app.include_router(pages.router)
    app.include_router(api.router)
    app.include_router(demo.router)
    app.include_router(subscriptions.router)
    app.include_router(review.router)
    app.include_router(shop_routes.router)
    return app


def build_capture(settings: Settings, app: FastAPI) -> Capturer:
    """Mock: static HTML capture (deterministic, no browser). Sandbox: live Playwright, static fallback (D-040)."""
    static = StaticCapture(app, ROOT_DIR / "shop" / "static" / "shop.css")
    return PlaywrightCapture(static) if settings.is_sandbox else static


def build_gateway(settings: Settings, store: JsonStore) -> PayPalGateway:
    """Pick the PayPal backends from APP_MODE / PAYPAL_TRANSPORT / PAYPAL_MERCHANT_MODE."""
    if not settings.is_sandbox:
        return PayPalGateway(settings, store)
    rest = PayPalRest(settings)
    sdk = SdkPayPal(settings, rest=rest)
    mcp = None
    if settings.paypal_transport == "mcp" and settings.paypal_merchant_mode == "single":
        mcp = McpPayPal(rest.token)
    return PayPalGateway(settings, store, sdk=sdk, mcp=mcp)


app = create_app()

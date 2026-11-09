"""FastAPI entry point: `uvicorn app.main:app --host 127.0.0.1 --port 8000` (1 worker)."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR, ConfigError, Settings, load_settings
from app.core.audit_log import mask_secrets
from app.routes import api, demo, pages
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

    store = JsonStore(settings.runtime_dir, settings.seed_dir, app_mode=settings.app_mode)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.ensure_all()
        async with store.aedit("state") as state:
            state.app_mode = settings.app_mode
        store.audit.append(
            actor="system", event="startup", reason=f"SubGuard started in {settings.app_mode} mode",
            details={"mode": settings.app_mode, "llm_provider": settings.active_llm_provider,
                     "llm_model": settings.llm_model},
        )
        log.info(f"SubGuard running in {settings.app_mode} mode at http://{settings.app_host}:{settings.app_port}/")
        yield

    app = FastAPI(title="SubGuard", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.mount("/static", StaticFiles(directory=ROOT_DIR / "app" / "static"), name="static")
    app.mount("/shop/static", StaticFiles(directory=ROOT_DIR / "shop" / "static"), name="shop_static")
    app.include_router(pages.router)
    app.include_router(api.router)
    app.include_router(demo.router)
    app.include_router(shop_routes.router)
    return app


app = create_app()

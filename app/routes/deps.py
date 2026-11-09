"""Small request helpers shared by routes."""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.store import JsonStore


def get_store(request: Request) -> JsonStore:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def integration_states(settings: Settings) -> dict[str, dict[str, str]]:
    """mock | sandbox | unavailable per integration. Live connectivity checks arrive with each integration."""
    if not settings.is_sandbox:
        return {
            "paypal": {"state": "mock", "transport": "mock"},
            "llm": {"state": "mock", "provider": "mock", "model": "fixtures"},
            "notify": {"state": "mock", "target": "outbox"},
            "capture": {"state": "mock"},
        }
    return {
        "paypal": {"state": "sandbox", "transport": settings.paypal_transport,
                   "merchant_mode": settings.paypal_merchant_mode},
        "llm": {"state": "sandbox", "provider": settings.llm_provider, "model": settings.llm_model},
        "notify": {"state": "sandbox" if settings.zapier_catch_hook_url else "mock",
                   "target": "zapier" if settings.zapier_catch_hook_url else "outbox"},
        "capture": {"state": "sandbox"},
    }

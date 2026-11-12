"""Optional sandbox smoke test (read-only): OAuth works and the seeded plans exist on PayPal's sandbox with the
billing cycles our `.env` prices describe. Never runs by default.

Run it with:  python -m pytest -m sandbox     (needs .env sandbox credentials and `make seed` first)
It's skipped when the credentials or the seeded plan ids are missing.
"""

from __future__ import annotations

import pytest
from dotenv import dotenv_values

from app.config import ROOT_DIR, Settings, validate_settings
from app.integrations.paypal_rest import PayPalRest
from app.integrations.paypal_types import plan_view
from app.models import SandboxIds

pytestmark = pytest.mark.sandbox


def sandbox_settings() -> Settings:
    env = ROOT_DIR / ".env"
    if not env.exists():
        pytest.skip("no .env file")
    # conftest.py forces mock-mode env vars (which beat .env), so pin these from the .env file itself
    values = dotenv_values(env)
    settings = Settings(_env_file=env, app_mode="sandbox", data_dir=ROOT_DIR / "data",  # type: ignore[call-arg]
                        llm_provider=values.get("LLM_PROVIDER") or "anthropic")
    if not (settings.paypal_client_id and settings.paypal_client_secret):
        pytest.skip("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET not set")
    return settings


async def test_sandbox_oauth_and_seeded_plans() -> None:
    settings = sandbox_settings()
    assert settings.paypal_api_base == "https://api-m.sandbox.paypal.com"
    ids_file = settings.runtime_dir / "sandbox_ids.json"
    if not ids_file.exists():
        pytest.skip("run `make seed` first (no sandbox_ids.json)")
    ids = SandboxIds.model_validate_json(ids_file.read_text(encoding="utf-8"))
    if "penwright-pro" not in ids.plans:
        pytest.skip("penwright-pro isn't seeded")
    rest = PayPalRest(settings)
    try:
        assert await rest.token()
        plan = plan_view(await rest.get_json(f"/v1/billing/plans/{ids.plans['penwright-pro']}"))
        prices = [c.price for c in plan.billing_cycles]
        p = settings.pricing
        assert prices == [0, p.penwright_intro_price, p.penwright_step_up_price]
        assert plan.status == "ACTIVE"
    finally:
        await rest.aclose()


def test_sandbox_settings_validate() -> None:
    settings = sandbox_settings()
    if not (settings.anthropic_api_key if settings.llm_provider == "anthropic" else settings.openai_api_key):
        pytest.skip(f"no API key for LLM_PROVIDER={settings.llm_provider}")
    validate_settings(settings)  # raises ConfigError naming any other missing variable

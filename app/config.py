"""Settings from environment / .env, plus startup validation (sandbox only, clear errors)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.pricing import Pricing, PricingFields

SANDBOX_API_BASE = "https://api-m.sandbox.paypal.com"
ROOT_DIR = Path(__file__).resolve().parent.parent
LLM_PROVIDERS = ("anthropic", "openai")


class ConfigError(RuntimeError):
    """Raised at startup when the configuration can't be used. The message is user-facing."""


MOCK_AUTOPAY_PATH = "/demo/paypal-autopay"


class Settings(BaseSettings, PricingFields):
    """Env / .env configuration. Demo prices and terms come from PricingFields (app/pricing.py)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_mode: Literal["mock", "sandbox"] = "mock"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    data_dir: Path = ROOT_DIR / "data"

    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    openai_reasoning_effort: str = ""  # empty = omit (model default); none|low|medium|high (D-119)
    llm_timeout_seconds: float = 30.0

    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_api_base: str = SANDBOX_API_BASE
    paypal_access_token: str = ""
    paypal_environment: str = "SANDBOX"
    paypal_transport: Literal["mcp", "sdk"] = "mcp"
    paypal_merchant_mode: Literal["single", "partner"] = "single"
    paypal_sandbox_buyer_email: str = ""
    paypal_sandbox_buyer_password: str = ""
    paypal_webhook_id: str = ""
    paypal_autopay_url: str = "https://www.sandbox.paypal.com/myaccount/autopay/"
    repo_url: str = "https://github.com/vishvinsartech/Paypal-hackathon-idea-3"  # footer "GitHub" + "MIT license" links

    zapier_catch_hook_url: str = ""
    log_all_requests: bool = False  # true: show every request in the terminal, including background polling
    demo_seed: bool = True  # mock mode: script Priya's Penwright usage on first start / reset
    render_api_key: str = ""

    @field_validator("llm_provider")
    @classmethod
    def _provider_lower(cls, v: str) -> str:
        return v.strip().lower()

    @property
    def pricing(self) -> Pricing:
        return Pricing(**{name: getattr(self, name) for name in PricingFields.model_fields})

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def seed_dir(self) -> Path:
        return self.data_dir / "seed"

    @property
    def is_sandbox(self) -> bool:
        return self.app_mode == "sandbox"

    @property
    def autopay_link(self) -> str:
        """A5: Layer 2's one-tap link. Sandbox: PayPal's Automatic payments page. Mock: a simulated copy."""
        return self.paypal_autopay_url if self.is_sandbox else MOCK_AUTOPAY_PATH

    @property
    def llm_model(self) -> str:
        if not self.is_sandbox:
            return "fixtures"
        return self.anthropic_model if self.llm_provider == "anthropic" else self.openai_model

    @property
    def active_llm_provider(self) -> str:
        return self.llm_provider if self.is_sandbox else "mock"


def validate_settings(s: Settings) -> None:
    """Fail fast with one clear message listing every problem."""
    problems: list[str] = []
    if s.llm_provider not in LLM_PROVIDERS:
        problems.append(f"LLM_PROVIDER={s.llm_provider!r} is not supported; use 'anthropic' or 'openai'.")
    if s.is_sandbox:
        if s.paypal_api_base.rstrip("/") != SANDBOX_API_BASE:
            problems.append(
                f"PAYPAL_API_BASE must be {SANDBOX_API_BASE} (SubGuard is sandbox only); "
                f"got {s.paypal_api_base!r}."
            )
        if s.paypal_environment.upper() != "SANDBOX":
            problems.append("PAYPAL_ENVIRONMENT must be SANDBOX.")
        required = {"PAYPAL_CLIENT_ID": s.paypal_client_id, "PAYPAL_CLIENT_SECRET": s.paypal_client_secret}
        if s.llm_provider == "anthropic":
            required |= {"ANTHROPIC_API_KEY": s.anthropic_api_key, "ANTHROPIC_MODEL": s.anthropic_model}
        elif s.llm_provider == "openai":
            required |= {"OPENAI_API_KEY": s.openai_api_key, "OPENAI_MODEL": s.openai_model}
        for name, value in required.items():
            if not value:
                problems.append(f"{name} is required in sandbox mode.")
    if problems:
        hint = " Set it in .env, or run with APP_MODE=mock (no keys needed)." if s.is_sandbox else ""
        raise ConfigError("SubGuard can't start: " + " ".join(problems) + hint)


def load_settings(**overrides: object) -> Settings:
    try:
        settings = Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"SubGuard can't start: invalid setting(s) in .env: {problems}") from None
    validate_settings(settings)
    return settings

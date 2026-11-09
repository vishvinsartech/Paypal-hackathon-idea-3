"""LLM provider selection: mock mode always uses fixtures; sandbox uses LLM_PROVIDER (validated at startup)."""

from __future__ import annotations

from app.config import ROOT_DIR, Settings
from app.llm.base import LLMProvider


def build_llm(settings: Settings) -> LLMProvider:
    if not settings.is_sandbox:
        from app.llm.mock_provider import MockProvider

        return MockProvider(ROOT_DIR / "data" / "fixtures" / "llm", settings.pricing)
    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model, settings.llm_timeout_seconds)
    from app.llm.openai_provider import OpenAIProvider

    return OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.llm_timeout_seconds)

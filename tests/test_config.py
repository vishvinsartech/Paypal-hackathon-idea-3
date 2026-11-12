from __future__ import annotations

import pytest

from app.config import ConfigError, Settings, validate_settings

SANDBOX_OK = dict(
    app_mode="sandbox", paypal_client_id="id", paypal_client_secret="secret",
    llm_provider="anthropic", anthropic_api_key="k", anthropic_model="model-x",
    demo_password="pw", session_secret="s" * 32,
)


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_mock_mode_needs_no_keys() -> None:
    s = make(app_mode="mock")
    validate_settings(s)
    assert s.active_llm_provider == "mock" and s.llm_model == "fixtures"


def test_sandbox_ok() -> None:
    s = make(**SANDBOX_OK)
    validate_settings(s)
    assert s.active_llm_provider == "anthropic" and s.llm_model == "model-x"


@pytest.mark.parametrize("field,var", [("demo_password", "DEMO_PASSWORD"), ("session_secret", "SESSION_SECRET")])
def test_sandbox_needs_the_sign_in_secrets(field: str, var: str) -> None:
    with pytest.raises(ConfigError, match=f"{var} is required in sandbox mode"):
        validate_settings(make(**{**SANDBOX_OK, field: ""}))


def test_mock_mode_starts_without_a_password_and_makes_a_session_secret() -> None:
    a, b = make(app_mode="mock"), make(app_mode="mock")
    validate_settings(a)
    assert a.demo_password == "" and a.session_hours == 8
    assert len(a.session_secret) >= 32 and a.session_secret != b.session_secret  # random per process


def test_sandbox_refuses_non_sandbox_base_url() -> None:
    with pytest.raises(ConfigError, match="PAYPAL_API_BASE"):
        validate_settings(make(**{**SANDBOX_OK, "paypal_api_base": "https://api-m.paypal.com"}))


def test_sandbox_missing_key_names_variable_and_suggests_mock() -> None:
    with pytest.raises(ConfigError) as exc:
        validate_settings(make(**{**SANDBOX_OK, "anthropic_api_key": ""}))
    assert "ANTHROPIC_API_KEY" in str(exc.value) and "APP_MODE=mock" in str(exc.value)


def test_sandbox_openai_requires_openai_vars() -> None:
    with pytest.raises(ConfigError) as exc:
        validate_settings(make(**{**SANDBOX_OK, "llm_provider": "openai"}))
    assert "OPENAI_API_KEY" in str(exc.value) and "OPENAI_MODEL" in str(exc.value)


def test_unknown_llm_provider() -> None:
    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        validate_settings(make(llm_provider="gemini"))


def test_env_example_parses_in_mock_mode(tmp_path) -> None:
    from app.config import ROOT_DIR

    s = Settings(_env_file=ROOT_DIR / ".env.example")  # type: ignore[call-arg]
    assert s.app_mode == "mock" and s.anthropic_api_key == "" and s.paypal_transport == "mcp"
    validate_settings(s)

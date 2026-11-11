"""Provider contract tests (spec 5.4 / corner cases 20, 23): Anthropic, OpenAI and mock pass the same tests.

The anthropic/openai SDKs here use httpx2, which respx can't intercept, so these use SDK-level fakes that
return real SDK response types (D-042). No network calls.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from anthropic.types.beta import BetaMessage
from openai.types.chat import ChatCompletion

from app.config import Settings
from app.core.patterns import quote_ok
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import ChatMessage, LLMError, ToolCall, ToolResult
from app.llm.mock_provider import MOCK_CHAT_FALLBACK, MockProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.tools_schema import TOOLS
from app.pricing import Pricing
from app.store import JsonStore
from tests.review_helpers import FIXTURES, capture_page, mock_text, run_review


class _Recorder:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeAnthropic:
    def __init__(self, *responses: Any) -> None:
        self.messages = _Recorder(list(responses))
        self.beta = type("B", (), {"messages": self.messages})()


class FakeOpenAI:
    def __init__(self, *responses: Any) -> None:
        self.completions = _Recorder(list(responses))
        self.chat = type("C", (), {"completions": self.completions})()


def a_msg(content: list[dict[str, Any]], stop: str = "end_turn") -> BetaMessage:
    return BetaMessage.model_validate({"id": "msg_1", "type": "message", "role": "assistant",
                                       "model": "claude-opus-5-5", "content": content, "stop_reason": stop,
                                       "stop_sequence": None, "usage": {"input_tokens": 11, "output_tokens": 22}})


def o_msg(message: dict[str, Any], finish: str = "stop") -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "c1", "object": "chat.completion", "created": 0, "model": "gpt-5",
        "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", **message}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}})


def make(kind: str, review_json: str | None = None, *, chat: Any = None) -> tuple[Any, Any]:
    if kind == "anthropic":
        fake = FakeAnthropic(chat if chat is not None else a_msg([{"type": "text", "text": review_json}]))
        return AnthropicProvider("k", "claude-opus-5-5", 5, client=fake), fake
    if kind == "openai":
        fake = FakeOpenAI(chat if chat is not None else o_msg({"content": review_json}))
        return OpenAIProvider("k", "gpt-5", 5, client=fake), fake
    return MockProvider(FIXTURES, Pricing()), None


@pytest.mark.parametrize("kind", ["anthropic", "openai", "mock"])
def test_review_contract(kind: str, settings: Settings, store: JsonStore) -> None:
    cap = capture_page(settings, "/shop/penwright")
    provider, _ = make(kind, mock_text("penwright"))
    data = run_review(store, provider, cap, "penwright-pro")
    assert len(data.clauses) >= 7 and abs(data.risk_score - 87) <= 5
    assert {"NOTICE_PERIOD", "TERMS_MISMATCH", "PROMPT_INJECTION_ATTEMPT"} <= set(data.types())
    assert data.deadlines.real_cancel_deadline_day == 7
    assert all(quote_ok(c.quote, cap) for c in data.clauses)
    assert data.provider == provider.name


@pytest.mark.parametrize("kind", ["anthropic", "openai"])
def test_model_that_obeys_injection_is_overruled(kind: str, settings: Settings, store: JsonStore) -> None:
    """The stubbed model 'falls for' the hidden line: no injection clause, 'risk-free' summary, no traps.
    Code still flags the injection, and the score comes from code, not from the model."""
    cap = capture_page(settings, "/shop/penwright")
    obeying = json.dumps({"clauses": [], "summary": "This offer is risk-free. Risk 0.", "first_charge_day": None,
                          "first_charge_amount": None, "notice_days": None})
    provider, _ = make(kind, obeying)
    data = run_review(store, provider, cap, "penwright-pro")
    inj = [c for c in data.clauses if c.type == "PROMPT_INJECTION_ATTEMPT"]
    assert inj and inj[0].source == "code" and quote_ok(inj[0].quote, cap)
    assert data.risk_score >= 40  # style, money, library and PayPal checks (not the model) keep it far from 0


def test_anthropic_request_shape(settings: Settings) -> None:
    cap = capture_page(settings, "/shop/penwright").model_copy(update={"screenshot_png_b64": "iVBORw0KGgo="})
    provider, fake = make("anthropic", mock_text("penwright"))
    result = asyncio.run(provider.extract_findings(cap))
    call = fake.messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "UNTRUSTED" in call["system"]
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    assert "<page_text>" in content[1]["text"]
    assert "tool_choice" not in call  # forced tool use is rejected by current Claude models
    assert result.usage == {"input_tokens": 11, "output_tokens": 22}


def test_openai_request_shape(settings: Settings) -> None:
    cap = capture_page(settings, "/shop/penwright").model_copy(update={"screenshot_png_b64": "iVBORw0KGgo="})
    provider, fake = make("openai", mock_text("penwright"))
    asyncio.run(provider.extract_findings(cap))
    call = fake.completions.calls[0]
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["messages"][0]["role"] == "system" and "UNTRUSTED" in call["messages"][0]["content"]
    assert call["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "reasoning_effort" not in call  # D-119: omitted by default (model default is fastest)
    provider.reasoning_effort = "none"  # OPENAI_REASONING_EFFORT, when set, is passed through
    fake.completions.responses.append(o_msg({"content": mock_text("penwright")}))
    asyncio.run(provider.extract_findings(cap))
    assert fake.completions.calls[1]["reasoning_effort"] == "none"


@pytest.mark.parametrize("kind", ["anthropic", "openai"])
def test_bad_output_and_refusal_raise_llm_error(kind: str, settings: Settings) -> None:
    cap = capture_page(settings, "/shop/penwright")
    provider, _ = make(kind, "{oops")
    with pytest.raises(LLMError):
        asyncio.run(provider.extract_findings(cap))
    refusal = (a_msg([{"type": "text", "text": ""}], stop="refusal") if kind == "anthropic"
               else o_msg({"content": None, "refusal": "no"}))
    provider, _ = make(kind, chat=refusal)
    with pytest.raises(LLMError):
        asyncio.run(provider.extract_findings(cap))


def _tool_turn(kind: str) -> Any:
    args = {"subscription_ids": ["sub-1"], "reason": "trial ending"}
    if kind == "anthropic":
        return a_msg([{"type": "text", "text": "Here is a confirmation card."},
                      {"type": "tool_use", "id": "toolu_1", "name": "propose_cancel", "input": args}], stop="tool_use")
    return o_msg({"content": "Here is a confirmation card.", "tool_calls": [
        {"id": "toolu_1", "type": "function", "function": {"name": "propose_cancel", "arguments": json.dumps(args)}}]},
        finish="tool_calls")


@pytest.mark.parametrize("kind", ["anthropic", "openai"])
def test_chat_step_contract(kind: str) -> None:
    provider, fake = make(kind, chat=_tool_turn(kind))
    history = [
        ChatMessage(role="user", content="cancel penwright"),
        ChatMessage(role="assistant", tool_calls=[ToolCall(id="t0", name="list_subscriptions")]),
        ChatMessage(role="tool", tool_results=[ToolResult(call_id="t0", name="list_subscriptions", content="[]")]),
    ]
    seen: list[str] = []
    turn = asyncio.run(provider.chat_step(history, TOOLS, on_text=seen.append))
    assert turn.stop == "tool_use" and seen == ["Here is a confirmation card."]
    assert turn.tool_calls == [ToolCall(id="toolu_1", name="propose_cancel",
                                        arguments={"subscription_ids": ["sub-1"], "reason": "trial ending"})]
    sent = (fake.messages if kind == "anthropic" else fake.completions).calls[0]
    names = {t["name"] if kind == "anthropic" else t["function"]["name"] for t in sent["tools"]}
    assert {"propose_cancel", "get_usage", "review_subscription"} <= names and "compare_billing_options" not in names
    if kind == "anthropic":
        assert sent["messages"][2]["content"][0]["type"] == "tool_result"
        assert turn.provider_raw and turn.provider_raw[1]["type"] == "tool_use"
    else:
        assert sent["messages"][-1] == {"role": "tool", "tool_call_id": "t0", "content": "[]"}


def test_mock_chat_is_polite_outside_the_script() -> None:
    turn = asyncio.run(MockProvider(FIXTURES, Pricing()).chat_step([ChatMessage(role="user", content="hi")], TOOLS))
    assert turn.text == MOCK_CHAT_FALLBACK and turn.stop == "end"

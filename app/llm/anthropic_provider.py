"""Anthropic adapter (Messages API via the `anthropic` SDK).

- Findings: image block (screenshot) + text, structured output via `output_config.format` json_schema
  (current Claude models reject forced `tool_choice`, so no forced tool call; D-041).
- Chat: client tools from tools_schema; assistant content is replayed verbatim (thinking blocks included).
- Models that support it get the server-side refusal fallback (`fallbacks: "default"`).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from app.integrations.capture import PageCapture
from app.llm.base import (
    AUDITOR_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT,
    NOTICE_JSON_SCHEMA,
    NOTICE_SYSTEM_PROMPT,
    ChatMessage,
    ChatTurn,
    EmailDraft,
    LLMError,
    NoticeContext,
    TextCallback,
    ToolCall,
    notice_user_prompt,
    parse_draft_json,
    parse_review_json,
    review_user_prompt,
)
from app.llm.tools_schema import ToolSpec, to_anthropic
from app.review_types import REVIEW_JSON_SCHEMA, ReviewResult

FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float, client: Any | None = None) -> None:
        self.model = model
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=1)

    async def _create(self, **kwargs: Any) -> Any:
        try:
            if self.model in FALLBACK_MODELS:
                return await self.client.beta.messages.create(
                    model=self.model, betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            return await self.client.messages.create(model=self.model, **kwargs)
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}") from None
        except anthropic.APIConnectionError:
            raise LLMError("Anthropic API unreachable") from None

    @staticmethod
    def _check(response: Any) -> dict[str, Any]:
        if response.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        usage = response.usage
        return {"input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None)}

    async def extract_findings(self, capture: PageCapture, *, feedback: str | None = None) -> ReviewResult:
        content: list[dict[str, Any]] = []
        if capture.screenshot_png_b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": capture.screenshot_png_b64}})
        content.append({"type": "text", "text": review_user_prompt(capture, feedback)})
        response = await self._create(
            max_tokens=16000, system=AUDITOR_SYSTEM_PROMPT, messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": REVIEW_JSON_SCHEMA}},
        )
        usage = self._check(response)
        if response.stop_reason == "max_tokens":
            raise LLMError("review output was cut off")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return parse_review_json(text, usage)

    @staticmethod
    def _messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                if m.provider_raw is not None:
                    out.append({"role": "assistant", "content": m.provider_raw})
                    continue
                blocks: list[dict[str, Any]] = [{"type": "text", "text": m.content}] if m.content else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                           for c in m.tool_calls]
                out.append({"role": "assistant", "content": blocks})
            else:  # all tool results in ONE user message
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
                    for r in m.tool_results]})
        return out

    async def chat_step(self, messages: list[ChatMessage], tools: list[ToolSpec], *,
                        on_text: TextCallback | None = None) -> ChatTurn:
        response = await self._create(
            max_tokens=16000, system=CHAT_SYSTEM_PROMPT, messages=self._messages(messages),
            tools=to_anthropic(tools), output_config={"effort": "low"},
        )
        usage = self._check(response)
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
                 for b in response.content if b.type == "tool_use"]
        if text and on_text:
            on_text(text)
        stop = "tool_use" if calls else ("max_tokens" if response.stop_reason == "max_tokens" else "end")
        raw = [json.loads(b.model_dump_json(exclude_none=True)) for b in response.content]
        return ChatTurn(text=text, tool_calls=calls, stop=stop, usage=usage, provider_raw=raw)

    async def draft_cancellation_notice(self, ctx: NoticeContext) -> EmailDraft:
        response = await self._create(
            max_tokens=2000, system=NOTICE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": notice_user_prompt(ctx)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": NOTICE_JSON_SCHEMA}},
        )
        self._check(response)
        if response.stop_reason == "max_tokens":
            raise LLMError("draft output was cut off")
        return parse_draft_json(next((b.text for b in response.content if b.type == "text"), ""))

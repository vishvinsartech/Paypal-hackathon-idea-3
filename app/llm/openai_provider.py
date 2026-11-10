"""OpenAI adapter (Chat Completions via the `openai` SDK).

- Findings: image_url (data URL) + text, `response_format` json_schema (strict).
- Chat: function tools; tool calls normalised to ToolCall; tool results sent as `role: tool` messages.
"""

from __future__ import annotations

import json
from typing import Any

import openai

from app.core.audit_log import mask_secrets
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
from app.llm.tools_schema import ToolSpec, to_openai
from app.review_types import REVIEW_JSON_SCHEMA, ReviewResult


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float, client: Any | None = None) -> None:
        self.model = model
        self.client = client or openai.AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=1)

    async def _create(self, **kwargs: Any) -> Any:
        try:
            return await self.client.chat.completions.create(model=self.model, **kwargs)
        except openai.APIStatusError as exc:  # keep OpenAI's reason (e.g. "organization must be verified")
            reason = str(getattr(exc, "message", "") or "").split(" Please go to")[0][:160]
            raise LLMError(f"OpenAI API error {exc.status_code}: {mask_secrets(reason)}") from None
        except openai.APIConnectionError:
            raise LLMError("OpenAI API unreachable") from None

    @staticmethod
    def _usage(response: Any) -> dict[str, Any]:
        u = response.usage
        return {"input_tokens": getattr(u, "prompt_tokens", None),
                "output_tokens": getattr(u, "completion_tokens", None)}

    async def extract_findings(self, capture: PageCapture, *, feedback: str | None = None) -> ReviewResult:
        content: list[dict[str, Any]] = [{"type": "text", "text": review_user_prompt(capture, feedback)}]
        if capture.screenshot_png_b64:
            content.insert(0, {"type": "image_url",
                               "image_url": {"url": f"data:image/png;base64,{capture.screenshot_png_b64}"}})
        response = await self._create(
            max_completion_tokens=16000,
            messages=[{"role": "system", "content": AUDITOR_SYSTEM_PROMPT}, {"role": "user", "content": content}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "review_result", "strict": True, "schema": REVIEW_JSON_SCHEMA}},
        )
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise LLMError("the model declined this request")
        if choice.finish_reason == "length":
            raise LLMError("review output was cut off")
        return parse_review_json(choice.message.content or "", self._usage(response))

    @staticmethod
    def _messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    msg["tool_calls"] = [{"id": c.id, "type": "function",
                                          "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                         for c in m.tool_calls]
                out.append(msg)
            else:
                out += [{"role": "tool", "tool_call_id": r.call_id, "content": r.content} for r in m.tool_results]
        return out

    async def chat_step(self, messages: list[ChatMessage], tools: list[ToolSpec], *,
                        on_text: TextCallback | None = None) -> ChatTurn:
        response = await self._create(max_completion_tokens=16000, messages=self._messages(messages),
                                      tools=to_openai(tools))
        choice = response.choices[0]
        calls = []
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError:
                args = {"_invalid_json": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        text = choice.message.content or ""
        if text and on_text:
            on_text(text)
        stop = "tool_use" if calls else ("max_tokens" if choice.finish_reason == "length" else "end")
        return ChatTurn(text=text, tool_calls=calls, stop=stop, usage=self._usage(response))

    async def draft_cancellation_notice(self, ctx: NoticeContext) -> EmailDraft:
        response = await self._create(
            max_completion_tokens=2000,
            messages=[{"role": "system", "content": NOTICE_SYSTEM_PROMPT},
                      {"role": "user", "content": notice_user_prompt(ctx)}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "email_draft", "strict": True, "schema": NOTICE_JSON_SCHEMA}},
        )
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise LLMError("the model declined this request")
        if choice.finish_reason == "length":
            raise LLMError("draft output was cut off")
        return parse_draft_json(choice.message.content or "")

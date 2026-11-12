"""Chat agent orchestrator (spec 7.3): a tool-use loop of at most 8 steps, the same for every provider.

Events go to `emit` as plain dicts, which the chat route streams over SSE:
  {"type": "text", "text": ...}            assistant text
  {"type": "tool", "name", "label", "ok"}  a tool-call chip
  {"type": "card", "card": {...}}          a confirmation card (from propose_cancel)
  {"type": "done"} | {"type": "error", "text": ...}
The model only proposes. Cancels happen when the user taps Confirm (/api/agent/confirm -> policy -> gateway).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.core.chat_tools import run_tool
from app.core.services import Services
from app.llm.base import ChatMessage, LLMError, LLMProvider
from app.llm.tools_schema import TOOLS

MAX_STEPS = 8
MAX_HISTORY = 12
Emit = Callable[[dict[str, Any]], None]


def build_messages(history: list[dict[str, str]], message: str) -> list[ChatMessage]:
    """Prior turns arrive as plain text (the browser keeps them); tool traffic isn't replayed."""
    msgs = [ChatMessage(role="user" if h.get("role") == "user" else "assistant", content=str(h.get("content", "")))
            for h in history[-MAX_HISTORY:] if h.get("content")]
    while msgs and msgs[0].role != "user":
        msgs.pop(0)
    return [*msgs, ChatMessage(role="user", content=message)]


async def run_chat(svc: Services, llm: LLMProvider, user_id: str, history: list[dict[str, str]], message: str,
                   emit: Emit) -> None:
    messages = build_messages(history, message)
    svc.store.audit.append(actor="user", event="chat_message", user_id=user_id,
                           details={"chars": len(message), "provider": llm.name})
    for step in range(MAX_STEPS):
        started = time.monotonic()
        try:
            turn = await llm.chat_step(messages, TOOLS, on_text=lambda t: emit({"type": "text", "text": t}))
        except LLMError as exc:
            _audit_llm(svc, llm, user_id, started, ok=False, error=str(exc), step=step)
            emit({"type": "error", "text": "The AI is unavailable right now, so I can't answer. "
                                           "Your subscriptions and safety timers still work."})
            return
        _audit_llm(svc, llm, user_id, started, ok=True, usage=turn.usage, step=step)
        messages.append(turn.as_message())
        if not turn.tool_calls:
            emit({"type": "done"})
            return
        results = []
        for call in turn.tool_calls:
            outcome = await run_tool(svc, user_id, call)
            results.append(outcome.result)
            emit({"type": "tool", "name": call.name, "label": outcome.label, "ok": not outcome.result.is_error})
            if outcome.card is not None:
                emit({"type": "card", "card": outcome.card.model_dump(mode="json")})
        messages.append(ChatMessage(role="tool", tool_results=results))
    emit({"type": "text", "text": "I stopped after 8 steps. Could you ask that in a simpler way?"})
    emit({"type": "done"})


def _audit_llm(svc: Services, llm: LLMProvider, user_id: str, started: float, *, ok: bool, step: int,
               usage: dict[str, Any] | None = None, error: str | None = None) -> None:
    """LLM call log: provider, model, latency, tokens, success. Never the prompt itself."""
    svc.store.audit.append(actor="agent", event="llm_call", user_id=user_id, result="ok" if ok else "error",
                           reason=error, details={"purpose": "chat", "provider": llm.name, "model": llm.model,
                                                  "latency_ms": round((time.monotonic() - started) * 1000),
                                                  "step": step, "usage": usage or {}})

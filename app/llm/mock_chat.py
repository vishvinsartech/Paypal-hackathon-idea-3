"""Scripted chat turns for mock mode (spec 7.3), from data/fixtures/llm/chat.json.

A script matches the user's message by keyword and is a list of steps:
  {"call": tool, "args": {...}}   one tool-use turn ("$sub" / "$merchant" are resolved, see below)
  {"say": "text {tool.field}"}     the final answer; {tool.field} is filled from that tool's RESULT (R7)
"$sub" is picked from the list_subscriptions result: the script's `merchant`, or (merchant "from_message")
the active subscriptions whose names match words in the message. Two or more matches -> a clarifying
question, never a guess (corner case 33). A tool error -> the answer explains it, and nothing is claimed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.llm.base import ChatMessage, ChatTurn, ToolCall

STOPWORDS = {"cancel", "please", "the", "one", "my", "subscription", "can", "you", "for", "me", "stop", "that",
             "this", "and", "app", "plan", "want", "to", "a", "it"}


def _results(messages: list[ChatMessage]) -> tuple[str, int, dict[str, dict[str, Any]], str | None]:
    """(user message, assistant turns since it, tool results by name, last error) for the current request."""
    idx = max(i for i, m in enumerate(messages) if m.role == "user")
    after = messages[idx + 1:]
    results: dict[str, dict[str, Any]] = {}
    error = None
    for m in after:
        for r in m.tool_results:
            data = json.loads(r.content)
            results[r.name] = data
            if r.is_error:
                error = data.get("error", "something went wrong")
    return messages[idx].content, sum(1 for m in after if m.role == "assistant"), results, error


def _pick(script: dict[str, Any], message: str, listing: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    active = [s for s in listing.get("subscriptions", []) if s["status"] == "ACTIVE"]
    want = script.get("merchant", "from_message")
    if want != "from_message":
        found = [s for s in active if s["merchant_id"] == want]
        return found[:1], want
    words = {w for w in re.findall(r"[a-z]+", message.lower()) if len(w) > 2 and w not in STOPWORDS}

    def text(s: dict[str, Any]) -> str:
        return f"{s['merchant']} {s['merchant_id']} {s['plan']} {s['merchant_about']}".lower()

    return [s for s in active if any(w in text(s) for w in words)], ""


def _fill(template: str, results: dict[str, dict[str, Any]]) -> str:
    def sub(m: re.Match[str]) -> str:
        value = results.get(m.group(1), {}).get(m.group(2))
        if value is None:
            raise KeyError(f"{m.group(1)}.{m.group(2)} missing from tool results")
        return str(value)
    return re.sub(r"\{(\w+)\.(\w+)\}", sub, template)


def _resolve(value: Any, sub_id: str, merchant: str) -> Any:
    if isinstance(value, list):
        return [_resolve(v, sub_id, merchant) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, sub_id, merchant) for k, v in value.items()}
    return {"$sub": sub_id, "$merchant": merchant}.get(value, value) if isinstance(value, str) else value


def scripted_turn(script: dict[str, Any], messages: list[ChatMessage]) -> ChatTurn:
    message, step, results, error = _results(messages)
    if error is not None:
        return ChatTurn(text=f"I couldn't do that: {error} Nothing was changed.")
    steps: list[dict[str, Any]] = script["steps"]
    sub_id, merchant = "", script.get("merchant", "")
    if "list_subscriptions" in results:
        picked, merchant = _pick(script, message, results["list_subscriptions"])
        if len(picked) > 1:
            names = " or ".join(f"{s['merchant']} ({s['plan']})" for s in picked)
            return ChatTurn(text=f"More than one subscription matches: {names}. Which one do you mean? "
                                 "I won't cancel anything until you tell me.")
        if not picked:
            return ChatTurn(text="I couldn't find an active subscription that matches. "
                                 "Check the subscriptions list, or tell me the merchant's name.")
        sub_id, merchant = picked[0]["subscription_id"], picked[0]["merchant_id"]
    if step >= len(steps):
        return ChatTurn(text="Done.")
    current = steps[step]
    if "say" in current:
        return ChatTurn(text=_fill(current["say"], results))
    call = ToolCall(id=f"mock-{step}", name=current["call"],
                    arguments=_resolve(current.get("args", {}), sub_id, merchant))
    return ChatTurn(tool_calls=[call], stop="tool_use")

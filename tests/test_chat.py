"""Chat agent (spec 7.3): scripted mock turns, tool chips, confirmation cards, guardrails (R1, R5, R7)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.llm.base import ChatMessage, ChatTurn, LLMError, ToolCall
from app.llm.tools_schema import ToolSpec
from tests.story_helpers import ACT_BY, add_user, advance_to, alerts, allow_many, audit, on, sub, subscribe


def chat(c: TestClient, message: str, user: str = "priya") -> list[dict[str, Any]]:
    res = c.post("/api/chat", json={"user_id": user, "message": message})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]


def text(events: list[dict[str, Any]]) -> str:
    return " ".join(e["text"] for e in events if e["type"] in ("text", "error"))


def cards(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["card"] for e in events if e["type"] == "card"]


def test_should_i_keep_penwright_numbers_from_code(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    events = chat(c, "Should I keep Penwright?")
    assert [e["name"] for e in events if e["type"] == "tool"] == [
        "list_subscriptions", "get_usage", "get_savings_estimate", "review_subscription"]
    answer = text(events)
    assert "You've opened Penwright Studio twice so far." in answer
    assert "the first paid year costs $524.88" in answer and f"{ACT_BY}." in answer
    assert cards(events) == [] and not audit(c, "confirm_token_issued")  # advice only, the decision is hers
    llm = audit(c, "llm_call", actor="agent")
    assert llm and llm[0]["details"]["provider"] == "mock" and "latency_ms" in llm[0]["details"]


def test_cancel_by_chat_needs_confirm_then_cancels(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    (card,) = cards(chat(c, "Cancel Penwright"))
    assert card["total_text"] == "$524.88/yr" and Decimal(card["total_per_year"]) == Decimal("524.88")
    assert card["items"][0]["merchant"] == "Penwright Studio" and "can't be undone" in card["warning"]
    pw_id = card["items"][0]["subscription_id"]
    assert sub(c, pw_id)["status"] == "ACTIVE"  # proposing never cancels
    assert not audit(c, "paypal_cancel", subscription_id=pw_id)
    done = c.post("/api/agent/confirm", json={"user_id": "priya", "token": card["token"],
                                              "subscription_ids": [pw_id]}).json()
    assert done["all_ok"] and done["results"][0]["transport"] == "mock"
    assert sub(c, pw_id)["status"] == "CANCELLED"
    assert audit(c, "paypal_cancel", subscription_id=pw_id, actor="user", rule_id="R1", result="ok")
    assert audit(c, "chat_tool_call", actor="agent", reason="propose_cancel")
    # the Day 5 check-in is now moot: no Keep / Cancel buttons left on it
    assert alerts(c, kind="reminder")[0]["acknowledged_at"] is not None


def test_ambiguous_cancel_asks_which_one(demo_client: TestClient) -> None:
    """Corner case 33: 'the writing one' matches two Penwright subscriptions -> ask, no card."""
    subscribe(allow_many(demo_client))
    subscribe(demo_client, review=False)
    events = chat(demo_client, "Cancel the writing one")
    assert "Which one do you mean?" in text(events) and cards(events) == []
    assert not audit(demo_client, "confirm_token_issued")


def test_cancel_by_name_gives_card(demo_client: TestClient) -> None:
    subscribe(demo_client)
    events = chat(demo_client, "Cancel Penwright")
    (card,) = cards(events)
    assert card["items"][0]["plan"] == "Penwright Pro" and card["total_text"] == "$524.88/yr"


def test_other_questions_get_mock_fallback(demo_client: TestClient) -> None:
    answer = text(chat(demo_client, "What's the weather?"))
    assert "sandbox" not in answer  # B11: no "switch to sandbox mode"; it names the chips instead
    for chip in ("Should I keep it?", "What happens if I do nothing?", "Draft my cancellation email"):
        assert chip in answer


def test_the_three_chips_have_scripted_answers(demo_client: TestClient) -> None:
    """B11: each suggested-question chip gets an answer built from tool results, and none of them acts."""
    c = demo_client
    subscribe(c)
    keep = text(chat(c, "Should I keep it?"))
    assert "the first paid year costs $524.88" in keep
    nothing = text(chat(c, "What happens if I do nothing?"))
    assert f"I ask you on {on(5)}" in nothing and f"cancels Penwright Studio in PayPal on {on(6)}" in nothing
    assert f"first charge on {on(11)}" in nothing and ACT_BY in nothing
    email = chat(c, "Draft my cancellation email")
    assert "quotes the notice clause word for word" in text(email) and cards(email) == []
    assert not audit(c, "confirm_token_issued") and not audit(c, "paypal_cancel")


def test_unknown_user_404(demo_client: TestClient) -> None:
    assert demo_client.post("/api/chat", json={"user_id": "mallory", "message": "hi"}).status_code == 404


class ScriptedLLM:
    """A fake provider that plays fixed turns (stands in for a real model trying things)."""

    name, model = "fake", "fake-1"

    def __init__(self, turns: list[ChatTurn]) -> None:
        self.turns = turns

    async def chat_step(self, messages: list[ChatMessage], tools: list[ToolSpec], *, on_text: Any = None) -> ChatTurn:
        turn = self.turns.pop(0)
        if turn.text and on_text:
            on_text(turn.text)
        return turn


def test_model_cannot_cancel_directly(demo_client: TestClient) -> None:
    """Corner case 29: a made-up 'cancel_subscription' tool is blocked (R1) and audited; nothing changes."""
    c = demo_client
    fw = subscribe(c)
    c.app.state.llm = ScriptedLLM([  # type: ignore[attr-defined]
        ChatTurn(tool_calls=[ToolCall(id="1", name="cancel_subscription", arguments={"subscription_id": fw["id"]})],
                 stop="tool_use"),
        ChatTurn(text="I can't cancel directly."),
    ])
    events = chat(c, "cancel everything now")
    assert [(e["name"], e["ok"]) for e in events if e["type"] == "tool"] == [("cancel_subscription", False)]
    assert audit(c, "policy_decision", rule_id="R1", decision="blocked", actor="policy")
    assert sub(c, fw["id"])["status"] == "ACTIVE"


def test_model_cannot_touch_other_users_subscription(demo_client: TestClient) -> None:
    """R5 through the agent: Priya's chat proposing another user's subscription -> error result, no card."""
    c = demo_client
    theirs = subscribe(c, user=add_user(c))
    c.app.state.llm = ScriptedLLM([  # type: ignore[attr-defined]
        ChatTurn(tool_calls=[ToolCall(id="1", name="propose_cancel",
                                      arguments={"subscription_ids": [theirs["id"]], "reason": "x"})], stop="tool_use"),
        ChatTurn(text="That one isn't yours."),
    ])
    events = chat(c, "cancel theirs")
    assert cards(events) == [] and [e["ok"] for e in events if e["type"] == "tool"] == [False]
    assert audit(c, "policy_decision", rule_id="R5", decision="blocked")


def test_too_many_in_one_command_blocked(demo_client: TestClient) -> None:
    c = demo_client
    c.app.state.llm = ScriptedLLM([  # type: ignore[attr-defined]
        ChatTurn(tool_calls=[ToolCall(id="1", name="propose_cancel",
                                      arguments={"subscription_ids": [f"s{i}" for i in range(11)], "reason": "x"})],
                 stop="tool_use"),
        ChatTurn(text="Too many."),
    ])
    assert cards(chat(c, "cancel all of them")) == []
    assert audit(c, "policy_decision", rule_id="R4", decision="blocked")


def test_llm_down_is_explained(demo_client: TestClient) -> None:
    class Down(ScriptedLLM):
        async def chat_step(self, *a: Any, **k: Any) -> ChatTurn:
            raise LLMError("timeout")

    demo_client.app.state.llm = Down([])  # type: ignore[attr-defined]
    events = chat(demo_client, "hello")
    assert events[-1]["type"] == "error" and "AI is unavailable" in events[-1]["text"]
    assert audit(demo_client, "llm_call", result="error")


def test_step_limit(demo_client: TestClient) -> None:
    loop = [ChatTurn(tool_calls=[ToolCall(id=str(i), name="list_subscriptions")], stop="tool_use") for i in range(9)]
    demo_client.app.state.llm = ScriptedLLM(loop)  # type: ignore[attr-defined]
    events = chat(demo_client, "loop forever")
    assert sum(1 for e in events if e["type"] == "tool") == 8 and "stopped after 8 steps" in text(events)


def test_schedule_reminder_fires_on_its_day(demo_client: TestClient) -> None:
    c = demo_client
    pw = subscribe(c)
    c.app.state.llm = ScriptedLLM([  # type: ignore[attr-defined]
        ChatTurn(tool_calls=[ToolCall(id="1", name="schedule_reminder",
                                      arguments={"subscription_id": pw["id"], "day": 3, "note": "Check Penwright"})],
                 stop="tool_use"),
        ChatTurn(text="I'll remind you on Day 3."),
    ])
    chat(c, "remind me on day 3")
    assert alerts(c, kind="reminder_note") == []
    advance_to(c, 3)
    advance_to(c, 3)
    notes = alerts(c, kind="reminder_note")
    assert len(notes) == 1 and notes[0]["body"] == "Check Penwright"

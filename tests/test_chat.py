"""Chat agent (spec 7.3): scripted mock turns, tool chips, confirmation cards, guardrails (R1, R5, R7)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.llm.base import ChatMessage, ChatTurn, LLMError, ToolCall
from app.llm.tools_schema import ToolSpec
from tests.story_helpers import advance_to, alerts, audit, sub, subscribe


def chat(c: TestClient, message: str, user: str = "priya") -> list[dict[str, Any]]:
    res = c.post("/api/chat", json={"user_id": user, "message": message})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]


def text(events: list[dict[str, Any]]) -> str:
    return " ".join(e["text"] for e in events if e["type"] in ("text", "error"))


def cards(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["card"] for e in events if e["type"] == "card"]


def test_framewise_worth_it_gives_228_card_and_confirm_cancels(demo_client: TestClient) -> None:
    c = demo_client
    advance_to(c, 21)
    c.post("/api/demo/price-rise")
    events = chat(c, "Is it still worth it? I barely used it.")
    assert [e["name"] for e in events if e["type"] == "tool"] == [
        "list_subscriptions", "get_usage", "get_savings_estimate", "propose_cancel"]
    assert "You opened it 3 times this month. Keeping it costs $228 a year." in text(events)
    (card,) = cards(events)
    assert card["total_text"] == "$228/yr" and Decimal(card["total_per_year"]) == Decimal("228.00")
    assert card["items"][0]["merchant"] == "Framewise" and "can't be undone" in card["warning"]
    fw_id = card["items"][0]["subscription_id"]
    assert sub(c, fw_id)["status"] == "ACTIVE"  # proposing never cancels
    assert not audit(c, "paypal_cancel", subscription_id=fw_id)
    done = c.post("/api/agent/confirm", json={"user_id": "priya", "token": card["token"],
                                              "subscription_ids": [fw_id]}).json()
    assert done["all_ok"] and done["results"][0]["transport"] == "mock"
    assert sub(c, fw_id)["status"] == "CANCELLED"
    assert audit(c, "paypal_cancel", subscription_id=fw_id, actor="user", rule_id="R1", result="ok")
    assert audit(c, "chat_tool_call", actor="agent", reason="propose_cancel")
    llm = audit(c, "llm_call", actor="agent")
    assert llm and llm[0]["details"]["provider"] == "mock" and "latency_ms" in llm[0]["details"]
    # the price-rise alert is now moot: no Keep / Cancel buttons left on it
    assert alerts(c, kind="price_rise")[0]["acknowledged_at"] is not None


def test_lumen_switch_to_yearly_numbers_from_code(demo_client: TestClient) -> None:
    advance_to(demo_client, 10)
    events = chat(demo_client, "Should I switch to yearly?", user="john")
    answer = text(events)
    assert "Monthly costs $240 a year. Yearly costs $200, so you'd save $40." in answer
    assert "on 9 of the last 10 days" in answer and "no partial refund" in answer
    assert cards(events) == []


def test_ambiguous_cancel_asks_which_one(demo_client: TestClient) -> None:
    """Corner case 33: 'the writing one' matches Penwright Pro and the AI Writing Pack -> ask, no card."""
    subscribe(demo_client, "penwright", "penwright-pro", addon_key="penwright-ai-pack")
    events = chat(demo_client, "Cancel the writing one")
    assert "Which one do you mean?" in text(events) and cards(events) == []
    assert not audit(demo_client, "confirm_token_issued")


def test_cancel_by_name_gives_card(demo_client: TestClient) -> None:
    subscribe(demo_client, "penwright", "penwright-pro")
    events = chat(demo_client, "Cancel Penwright")
    (card,) = cards(events)
    assert card["items"][0]["plan"] == "Penwright Pro" and card["total_text"] == "$524.88/yr"


def test_other_questions_get_mock_fallback(demo_client: TestClient) -> None:
    assert "switch to sandbox mode for free chat" in text(chat(demo_client, "What's the weather?"))


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
    fw = c.get("/api/subscriptions?user=priya").json()[0]
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
    """R5 through the agent: Priya's chat proposing John's Lumen -> error result, no card, no token."""
    c = demo_client
    lumen = c.get("/api/subscriptions?user=john").json()[0]
    c.app.state.llm = ScriptedLLM([  # type: ignore[attr-defined]
        ChatTurn(tool_calls=[ToolCall(id="1", name="propose_cancel",
                                      arguments={"subscription_ids": [lumen["id"]], "reason": "x"})], stop="tool_use"),
        ChatTurn(text="That one isn't yours."),
    ])
    events = chat(c, "cancel Lumen")
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
    fw = c.get("/api/subscriptions?user=priya").json()[0]
    c.app.state.llm = ScriptedLLM([  # type: ignore[attr-defined]
        ChatTurn(tool_calls=[ToolCall(id="1", name="schedule_reminder",
                                      arguments={"subscription_id": fw["id"], "day": 3, "note": "Check Framewise"})],
                 stop="tool_use"),
        ChatTurn(text="I'll remind you on Day 3."),
    ])
    chat(c, "remind me on day 3")
    assert alerts(c, kind="reminder_note") == []
    advance_to(c, 3)
    advance_to(c, 3)
    notes = alerts(c, kind="reminder_note")
    assert len(notes) == 1 and notes[0]["body"] == "Check Framewise"

"""Mock LLM (mock mode): deterministic fixture answers from data/fixtures/llm/.

Review fixtures use `{{token}}` placeholders filled from the .env pricing, so quotes stay verbatim substrings
of the shop pages whatever the demo prices are. Chat fixtures are scripted turns for the demo prompts
(see mock_chat.py); anything else gets the polite "mock mode" answer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.integrations.capture import PageCapture
from app.llm.base import ChatMessage, ChatTurn, LLMError, TextCallback, parse_review_json
from app.llm.mock_chat import scripted_turn
from app.llm.tools_schema import ToolSpec
from app.pricing import Pricing
from app.review_types import ReviewResult

MOCK_CHAT_FALLBACK = "In mock mode I can answer the demo questions; switch to sandbox mode for free chat."


def pricing_tokens(p: Pricing) -> dict[str, str]:
    return {
        "trial_days": str(p.penwright_trial_days), "first_charge_day": str(p.penwright_first_charge_day),
        "intro": p.money(p.penwright_intro_price), "intro_raw": str(p.penwright_intro_price),
        "intro_months": str(p.penwright_intro_months), "step_up": p.money(p.penwright_step_up_price),
        "notice_days": str(p.penwright_notice_days), "export_limit": str(p.penwright_export_limit),
    }


def render_fixture(text: str, tokens: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in tokens:
            raise KeyError(f"unknown fixture token {key!r}")
        return json.dumps(tokens[key])[1:-1]  # JSON-escape inside the string
    return re.sub(r"\{\{(\w+)\}\}", sub, text)


class MockProvider:
    name = "mock"
    model = "fixtures"

    def __init__(self, fixtures_dir: Path, pricing: Pricing) -> None:
        self.dir = fixtures_dir
        self.tokens = pricing_tokens(pricing)

    def review_fixture_text(self, merchant_id: str) -> str:
        path = self.dir / f"{merchant_id}.json"
        if not path.exists():
            raise LLMError(f"no mock review fixture for {merchant_id!r}")
        return render_fixture(path.read_text(encoding="utf-8"), self.tokens)

    async def extract_findings(self, capture: PageCapture, *, feedback: str | None = None) -> ReviewResult:
        return parse_review_json(self.review_fixture_text(capture.merchant_id), {"input_tokens": 0, "output_tokens": 0})

    def _chat_fixtures(self) -> list[dict[str, Any]]:
        path = self.dir / "chat.json"
        if not path.exists():
            return []
        return json.loads(render_fixture(path.read_text(encoding="utf-8"), self.tokens)).get("scripts", [])

    async def chat_step(self, messages: list[ChatMessage], tools: list[ToolSpec], *,
                        on_text: TextCallback | None = None) -> ChatTurn:
        user = next((m.content.lower() for m in reversed(messages) if m.role == "user"), "")
        script = next((s for s in self._chat_fixtures() if any(k in user for k in s.get("match", []))), None)
        turn = scripted_turn(script, messages) if script else ChatTurn(text=MOCK_CHAT_FALLBACK)
        turn.usage = {"input_tokens": 0, "output_tokens": 0}
        if turn.text and on_text:
            on_text(turn.text)
        return turn

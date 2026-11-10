"""Chat-agent tool definitions, defined once as Pydantic models (spec 7.3) and converted per provider.

All tools are propose-only: `propose_cancel` returns a confirmation card + token, it never cancels.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NoArgs(BaseModel):
    pass


class SubscriptionArg(BaseModel):
    subscription_id: str = Field(description="SubGuard subscription id, e.g. sub-I-ABC123")


class UsageArgs(SubscriptionArg):
    days: int = Field(30, ge=1, le=365, description="How many past sim days to count")


class ProposeCancelArgs(BaseModel):
    subscription_ids: list[str] = Field(description="Subscriptions to cancel (max 10)")
    reason: str = Field(description="Short reason shown to the user")


class ReminderArgs(SubscriptionArg):
    day: int = Field(description="Sim day to remind on")
    note: str = ""


class AlertArgs(BaseModel):
    title: str
    body: str
    subscription_id: str | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    args: type[BaseModel]

    def json_schema(self) -> dict[str, Any]:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("properties", {})
        schema["type"] = "object"
        return schema


TOOLS: list[ToolSpec] = [
    ToolSpec(name="list_subscriptions", description="List the current user's subscriptions.", args=NoArgs),
    ToolSpec(name="get_subscription", description="Get one subscription with status, price and timers.",
             args=SubscriptionArg),
    ToolSpec(name="get_usage", description="How often the user opened the app in the last N days.", args=UsageArgs),
    ToolSpec(name="get_savings_estimate", description="Money at stake per year if this subscription continues.",
             args=SubscriptionArg),
    ToolSpec(name="review_subscription", description="Get the fine-print review and risk score.",
             args=SubscriptionArg),
    ToolSpec(name="propose_cancel", description="Propose cancelling subscriptions. Returns a confirmation card; "
             "nothing is cancelled until the user taps Confirm.", args=ProposeCancelArgs),
    ToolSpec(name="keep_subscription", description="Record that the user wants to keep a subscription.",
             args=SubscriptionArg),
    ToolSpec(name="schedule_reminder", description="Schedule a reminder on a sim day.", args=ReminderArgs),
    ToolSpec(name="send_alert", description="Send the user an in-app alert.", args=AlertArgs),
]


def to_anthropic(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "input_schema": t.json_schema()} for t in tools]


def to_openai(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.json_schema()}} for t in tools]

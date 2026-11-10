"""The chat agent's tools (spec 7.3). Propose-only: nothing here writes to PayPal.

Every number in a tool result comes from code (PayPal plans, usage.json), never from the LLM (R7).
Every subscription id is ownership-checked (R5). `propose_cancel` returns a confirmation card + token;
only the user's Confirm tap (`/api/agent/confirm`) can cancel.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core import timers as tm
from app.core.actions import ConfirmCard, propose_cancel, year_cost
from app.core.alerts import send_alert
from app.core.policy import Decision
from app.core.savings import compare_billing
from app.core.services import Services
from app.core.usage import days_used, last_open_day, opens_between, times
from app.integrations.paypal_gateway import Ctx
from app.integrations.paypal_types import PayPalError
from app.llm.base import ToolCall, ToolResult
from app.llm.tools_schema import TOOLS
from app.models import Reminder, Subscription

SPECS = {t.name: t for t in TOOLS}


class ToolError(Exception):
    pass


class ToolOutcome(BaseModel):
    result: ToolResult
    card: ConfirmCard | None = None
    label: str = ""


def _own(svc: Services, user_id: str, sub_id: str, tool: str) -> Subscription:
    sub = svc.sub(sub_id)
    if sub is None or sub.owner_id != user_id:
        svc.policy.record(svc.store, Decision(allowed=False, rule_id="R5", subscription_id=sub_id,
                                              reason="You can only act on your own subscriptions"),
                          user_id=user_id, action=f"chat:{tool}", requested_by="agent")
        raise ToolError("That subscription isn't yours (or doesn't exist).")
    return sub


def _sub_row(svc: Services, sub: Subscription) -> dict[str, Any]:
    merchant = svc.merchant(sub.merchant_id)
    plan = next((p for p in merchant.plans if p.key == sub.plan_key), None)
    price = sub.consent_snapshot.price if sub.consent_snapshot else None
    return {"subscription_id": sub.id, "merchant_id": merchant.id, "merchant": merchant.name,
            "merchant_about": merchant.tagline, "plan": plan.name if plan else sub.plan_key,
            "plan_key": sub.plan_key, "addon": bool(sub.addon_of), "status": sub.status, "essential": sub.essential,
            "next_billing_day": sub.next_billing_day,
            "agreed_price_text": svc.money(price) if price is not None else None}


async def t_list(svc: Services, user_id: str, _a: dict[str, Any]) -> dict[str, Any]:
    subs = [s for s in svc.store.load("subscriptions").items if s.owner_id == user_id]
    return {"today": svc.day, "subscriptions": [_sub_row(svc, s) for s in subs]}


async def t_get(svc: Services, user_id: str, a: dict[str, Any]) -> dict[str, Any]:
    sub = _own(svc, user_id, a["subscription_id"], "get_subscription")
    timers = [{"kind": t.kind, "fire_day": t.fire_day, "status": t.status, "deadline_day": t.deadline_day}
              for t in svc.store.load("timers").items if t.subscription_id == sub.id]
    per_year = await year_cost(svc, sub)
    return {**_sub_row(svc, sub), "timers": timers, "cost_per_year_now_text": svc.money(per_year)}


async def t_usage(svc: Services, user_id: str, a: dict[str, Any]) -> dict[str, Any]:
    sub = _own(svc, user_id, a["subscription_id"], "get_usage")
    days, today = int(a.get("days", 30)), svc.day
    opens = opens_between(svc.store, user_id, sub.merchant_id, today - days + 1, today)
    last = last_open_day(svc.store, user_id, sub.merchant_id, today)
    return {"merchant": svc.merchant(sub.merchant_id).name, "window_days": days, "opens": opens,
            "opens_text": times(opens), "days_used": days_used(svc.store, user_id, sub.merchant_id, days, today),
            "last_open_day": last, "days_since_last_open": None if last is None else today - last}


async def t_savings(svc: Services, user_id: str, a: dict[str, Any]) -> dict[str, Any]:
    sub = _own(svc, user_id, a["subscription_id"], "get_savings_estimate")
    per_year = await year_cost(svc, sub)
    return {"merchant": svc.merchant(sub.merchant_id).name, "per_year": str(per_year),
            "per_year_text": svc.money(per_year), "basis": "current PayPal plan, first paid year"}


async def t_compare(svc: Services, user_id: str, a: dict[str, Any]) -> dict[str, Any]:
    try:
        merchant = svc.merchant(str(a["merchant"]).lower())
    except StopIteration:
        raise ToolError("Unknown merchant.") from None
    plans = {p.billing_cycles[-1].interval_unit: p for p in merchant.plans if not p.addon}
    if "MONTH" not in plans or "YEAR" not in plans:
        raise ToolError(f"{merchant.name} doesn't offer both monthly and yearly billing.")
    ctx = Ctx(actor="agent", user_id=user_id, merchant=merchant)
    try:
        monthly = await svc.gw.get_plan(svc.gw.plan_id(plans["MONTH"].key), ctx)
        yearly = await svc.gw.get_plan(svc.gw.plan_id(plans["YEAR"].key), ctx)
    except PayPalError as exc:
        raise ToolError(f"PayPal didn't return the plans ({exc.summary()}).") from None
    cmp = compare_billing(monthly.billing_cycles, yearly.billing_cycles)
    out: dict[str, Any] = {"merchant": merchant.name}
    for k, v in cmp.items():
        out[k], out[f"{k}_text"] = str(v), svc.money(v)
    out["yearly_terms"] = "Paid up front; no partial refund if cancelled (from the merchant's terms)."
    return out


async def t_review(svc: Services, user_id: str, a: dict[str, Any]) -> dict[str, Any]:
    sub = _own(svc, user_id, a["subscription_id"], "review_subscription")
    review = tm.review_for(svc, sub)
    if review is None:
        raise ToolError("No fine-print review exists for this subscription.")
    d = review.data
    return {"merchant": svc.merchant(sub.merchant_id).name, "risk_score": d.risk_score, "summary": d.summary,
            "mode": d.mode_label, "real_cancel_deadline_day": d.deadlines.real_cancel_deadline_day,
            "first_charge_day": d.deadlines.first_charge_day,
            "findings": [{"type": c.type, "plain_english": c.plain_english} for c in d.clauses]}


async def t_keep(svc: Services, user_id: str, a: dict[str, Any]) -> dict[str, Any]:
    _own(svc, user_id, a["subscription_id"], "keep_subscription")
    return (await tm.keep(svc, user_id, a["subscription_id"])).model_dump()


async def t_reminder(svc: Services, user_id: str, a: dict[str, Any]) -> dict[str, Any]:
    sub = _own(svc, user_id, a["subscription_id"], "schedule_reminder")
    day = int(a["day"])
    if day <= svc.day:
        raise ToolError(f"Pick a day after today (Day {svc.day}).")
    rem = Reminder(id=f"rm-{secrets.token_hex(4)}", user_id=user_id, subscription_id=sub.id, day=day,
                   note=str(a.get("note", ""))[:200])
    async with svc.store.aedit("state") as state:
        state.reminders.append(rem)
    svc.store.audit.append(actor="agent", event="reminder_scheduled", user_id=user_id, subscription_id=sub.id,
                           details={"day": day, "reminder_id": rem.id})
    return {"scheduled": True, "day": day, "merchant": svc.merchant(sub.merchant_id).name}


async def t_alert(svc: Services, user_id: str, a: dict[str, Any]) -> dict[str, Any]:
    sid = a.get("subscription_id")
    if sid:
        _own(svc, user_id, sid, "send_alert")
    alert, _ = await send_alert(svc, user_id=user_id, key=f"chat:{secrets.token_hex(5)}", kind="chat_note",
                                level="info", title=str(a["title"])[:120], body=str(a["body"])[:500],
                                subscription_id=sid)
    return {"sent": True, "alert_id": alert.id, "delivery": alert.delivery}


async def t_propose(svc: Services, user_id: str, a: dict[str, Any]) -> tuple[dict[str, Any], ConfirmCard]:
    ids = list(dict.fromkeys(a.get("subscription_ids") or []))
    card = await propose_cancel(svc, user_id, ids, str(a.get("reason") or "Cancelled from the SubGuard chat"))
    if isinstance(card, Decision):
        raise ToolError(f"Blocked by rule {card.rule_id}: {card.reason}")
    return {"proposed": True, "cancelled": False, "note": "Nothing is cancelled until the user taps Confirm.",
            "merchants": ", ".join(i.merchant for i in card.items), "total_per_year_text": card.total_text,
            "items": [{"merchant": i.merchant, "per_year_text": i.per_year_text} for i in card.items]}, card


HANDLERS = {"list_subscriptions": t_list, "get_subscription": t_get, "get_usage": t_usage,
            "get_savings_estimate": t_savings, "compare_billing_options": t_compare,
            "review_subscription": t_review, "keep_subscription": t_keep, "schedule_reminder": t_reminder,
            "send_alert": t_alert}
LABELS = {"list_subscriptions": "subscriptions", "get_subscription": "subscription", "get_usage": "usage",
          "get_savings_estimate": "savings", "compare_billing_options": "billing options",
          "review_subscription": "fine-print review", "propose_cancel": "confirmation card",
          "keep_subscription": "keep", "schedule_reminder": "reminder", "send_alert": "alert"}


async def run_tool(svc: Services, user_id: str, call: ToolCall) -> ToolOutcome:
    """Run one tool call; errors (including policy blocks) come back as is_error results the agent can explain."""
    card: ConfirmCard | None = None
    spec = SPECS.get(call.name)
    try:
        if spec is None:  # corner case 29: e.g. the model tries a direct "cancel_subscription"
            svc.policy.record(svc.store, Decision(allowed=False, rule_id="R1",
                                                  reason=f"Unknown tool {call.name!r}: the agent can only propose"),
                              user_id=user_id, action=f"chat:{call.name}", requested_by="agent")
            raise ToolError("That tool doesn't exist. I can only propose a cancel; the user confirms it.")
        try:
            args = spec.args.model_validate(call.arguments).model_dump()
        except ValidationError as exc:
            raise ToolError(f"Bad arguments: {exc.error_count()} problem(s).") from None
        if call.name == "propose_cancel":
            data, card = await t_propose(svc, user_id, args)
        else:
            data = await HANDLERS[call.name](svc, user_id, args)
        ok, content = True, json.dumps(data, default=str)
    except ToolError as exc:
        ok, content = False, json.dumps({"error": str(exc)})
    svc.store.audit.append(actor="agent", event="chat_tool_call", user_id=user_id, result="ok" if ok else "error",
                           decision="n/a", reason=call.name,
                           subscription_id=call.arguments.get("subscription_id") if call.arguments else None,
                           details={"tool": call.name, "arguments": call.arguments,
                                    **({"error": json.loads(content)["error"]} if not ok else {})})
    return ToolOutcome(result=ToolResult(call_id=call.id, name=call.name, content=content, is_error=not ok),
                       card=card, label=LABELS.get(call.name, call.name))

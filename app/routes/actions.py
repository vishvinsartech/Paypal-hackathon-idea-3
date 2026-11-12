"""User actions: confirmation cards + confirm (R1/R3), alert buttons, Keep, essential tag, timers, KPIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import timers as tm
from app.core.actions import cancel_confirmed, propose_cancel
from app.core.policy import Decision
from app.core.savings import charges_avoided, money_protected, protected_by_currency
from app.core.services import Services
from app.models import Alert, Timer
from app.store import utcnow

router = APIRouter(prefix="/api")
DARK_TYPES_EXCLUDED = {"CLEAR_TERMS", "AUTO_RENEW"}


def get_services(request: Request) -> Services:
    return request.app.state.services


def blocked(d: Decision) -> JSONResponse:
    return JSONResponse({"blocked": True, "rule_id": d.rule_id, "reason": d.reason}, status_code=403)


class ProposeIn(BaseModel):
    user_id: str
    subscription_ids: list[str]
    reason: str = "Cancelled from SubGuard"


class ConfirmIn(BaseModel):
    user_id: str
    token: str | None = None
    subscription_ids: list[str]


@router.post("/agent/propose", response_model=None)
async def propose(body: ProposeIn, svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    card = await propose_cancel(svc, body.user_id, body.subscription_ids, body.reason)
    return blocked(card) if isinstance(card, Decision) else card.model_dump(mode="json")


@router.post("/agent/confirm", response_model=None)
async def confirm(body: ConfirmIn, svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    results = await cancel_confirmed(svc, body.user_id, body.subscription_ids, body.token)
    if isinstance(results, Decision):
        return blocked(results)
    return {"results": [r.model_dump(mode="json") for r in results], "all_ok": all(r.ok for r in results)}


class ActIn(BaseModel):
    user_id: str
    action: str


async def _ack(svc: Services, alert_id: str) -> None:
    async with svc.store.aedit("alerts") as alerts:
        a = next(x for x in alerts.items if x.id == alert_id)
        a.acknowledged_at = a.acknowledged_at or utcnow()


@router.post("/alerts/{alert_id}/act", response_model=None)
async def act(alert_id: str, body: ActIn, svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    alert = next((a for a in svc.store.load("alerts").items if a.id == alert_id), None)
    if alert is None:
        raise HTTPException(404, "Unknown alert")
    if alert.user_id != body.user_id:
        return blocked(svc.policy.record(svc.store, Decision(allowed=False, rule_id="R5", reason="Not your alert",
                                                             subscription_id=alert.subscription_id),
                                         user_id=body.user_id, action=f"alert:{body.action}", requested_by="user"))
    allowed = {a["action"] for a in alert.actions} | {"ack"}
    if body.action not in allowed:
        raise HTTPException(400, "That action isn't offered on this alert")
    sid = alert.subscription_id or ""
    svc.store.audit.append(actor="user", event="alert_action", user_id=body.user_id,
                           subscription_id=alert.subscription_id,
                           details={"alert_id": alert_id, "action": body.action, "kind": alert.kind})
    out: dict[str, Any]
    if body.action == "keep":
        out = (await tm.keep(svc, body.user_id, sid)).model_dump()
    elif body.action == "cancel":
        card = await propose_cancel(svc, body.user_id, [sid], "Cancelled from an alert")
        if isinstance(card, Decision):
            return blocked(card)
        return {"confirm": card.model_dump(mode="json")}  # the UI's tap then calls /api/agent/confirm
    elif body.action == "review_email":
        offered = next((a for a in alert.actions if a["action"] == "review_email"), {})
        out = {"notice_id": offered.get("notice_id")}  # the UI opens the email preview
    elif body.action == "open_autopay":
        out = {"url": svc.settings.autopay_link}
    else:
        out = {"status": "acknowledged"}
    await _ack(svc, alert_id)
    return out


class KeepIn(BaseModel):
    user_id: str


class EssentialIn(BaseModel):
    user_id: str
    essential: bool


@router.post("/subscriptions/{sub_id}/keep")
async def keep_sub(sub_id: str, body: KeepIn, svc: Services = Depends(get_services)) -> dict[str, Any]:
    return (await tm.keep(svc, body.user_id, sub_id)).model_dump()


@router.post("/subscriptions/{sub_id}/essential", response_model=None)
async def essential(sub_id: str, body: EssentialIn,
                    svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    sub = svc.sub(sub_id)
    if sub is None or sub.owner_id != body.user_id:
        return blocked(svc.policy.record(svc.store, Decision(allowed=False, rule_id="R5", subscription_id=sub_id,
                                                             reason="You can only act on your own subscriptions"),
                                         user_id=body.user_id, action="tag_essential", requested_by="user"))
    async with svc.store.aedit("subscriptions") as subs:
        next(s for s in subs.items if s.id == sub_id).essential = body.essential
    svc.store.audit.append(actor="user", event="essential_tag", user_id=body.user_id, subscription_id=sub_id,
                           rule_id="R6", details={"essential": body.essential})
    return {"subscription_id": sub_id, "essential": body.essential}


@router.get("/alerts")
def list_alerts(user: str = "priya", svc: Services = Depends(get_services)) -> list[Alert]:
    return sorted((a for a in svc.store.load("alerts").items if a.user_id == user), key=lambda a: a.created_at,
                  reverse=True)


@router.get("/timers")
def list_timers(user: str = "priya", svc: Services = Depends(get_services)) -> list[Timer]:
    mine = {s.id for s in svc.store.load("subscriptions").items if s.owner_id == user}
    return [t for t in svc.store.load("timers").items if t.subscription_id in mine]


@router.get("/kpis")
def kpis(user: str = "priya", svc: Services = Depends(get_services)) -> dict[str, Any]:
    subs = [s for s in svc.store.load("subscriptions").items if s.owner_id == user]
    ids = {s.id for s in subs}
    reviews = [r for r in svc.store.load("reviews").items if r.subscription_id in ids]
    caught = sum(1 for r in reviews for c in r.data.clauses if c.type not in DARK_TYPES_EXCLUDED)
    cur = svc.settings.pricing.demo_currency
    protected = money_protected(subs, user, cur)
    others = {c: v for c, v in protected_by_currency(subs, user).items() if c != cur}
    avoided = charges_avoided(subs, user, cur)
    return {"charges_avoided": str(avoided), "charges_avoided_text": svc.money(avoided),  # D10 primary figure
            "year_one_text": f"up to {svc.money(protected)} in year one",
            "money_protected": str(protected), "money_protected_text": svc.money(protected), "currency": cur,
            "other_currencies": {c: svc.settings.pricing.money(v, c) for c, v in others.items()},
            "dark_patterns_caught": caught,
            "subscriptions_cancelled": sum(1 for s in subs if s.cancelled_by in ("user", "timer")),
            "active_watches": sum(1 for s in subs if s.status == "ACTIVE")}

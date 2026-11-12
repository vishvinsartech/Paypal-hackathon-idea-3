"""Layer 2 routes (A5): SubGuard's read-only PayPal check while Priya cancels in PayPal, and (mock mode only) the
simulated PayPal Automatic payments page that the one-tap link opens."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import ROOT_DIR
from app.core.layer2 import check_paypal
from app.core.policy import Decision
from app.core.services import Services
from app.integrations.paypal_types import PayPalError
from app.routes.actions import get_services

router = APIRouter()
templates = Jinja2Templates(directory=ROOT_DIR / "app" / "templates")


def _own(svc: Services, sub_id: str, user: str, action: str) -> Any:
    sub = svc.sub(sub_id)
    if sub is None or sub.owner_id != user:  # R5
        d = svc.policy.record(svc.store, Decision(allowed=False, rule_id="R5", subscription_id=sub_id,
                                                  reason="You can only check your own subscriptions"),
                              user_id=user, action=action, requested_by="user")
        return JSONResponse({"blocked": True, "rule_id": d.rule_id, "reason": d.reason}, status_code=403)
    return sub


@router.post("/api/subscriptions/{sub_id}/check-paypal", response_model=None)
async def check_paypal_status(sub_id: str, user: str = "priya",
                              svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    """A5 polling: the ACTION NEEDED card calls this every few seconds until PayPal shows CANCELLED."""
    sub = _own(svc, sub_id, user, "check_paypal")
    if isinstance(sub, JSONResponse):
        return sub
    status, debug_id = await check_paypal(svc, sub)
    return {"subscription_id": sub.id, "status": status, "cancelled": status == "CANCELLED",
            "paypal_debug_id": debug_id}


def _mock_only(svc: Services) -> None:
    if svc.settings.is_sandbox or svc.gw.mock is None:
        raise HTTPException(404, "Only in demo data mode; sandbox mode links to PayPal's real page")


@router.get("/demo/paypal-autopay", response_class=HTMLResponse)
def mock_autopay(request: Request, user: str = "priya", svc: Services = Depends(get_services)) -> HTMLResponse:
    """Stand-in for PayPal's Automatic payments page (mock mode). Clearly labelled as simulated."""
    _mock_only(svc)
    subs = [s for s in svc.store.load("subscriptions").items if s.owner_id == user and s.status == "ACTIVE"]
    rows = [{"id": s.id, "paypal_id": s.paypal_id, "merchant": svc.merchant(s.merchant_id).name,
             "price": svc.money(s.consent_snapshot.price) if s.consent_snapshot else ""} for s in subs]
    return templates.TemplateResponse(request, "mock_autopay.html", {"rows": rows, "user": user})


class AutopayCancelIn(BaseModel):
    user_id: str = "priya"
    subscription_id: str


@router.post("/api/demo/paypal-autopay/cancel", response_model=None)
async def mock_autopay_cancel(body: AutopayCancelIn,
                              svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    """Priya presses Cancel on the simulated PayPal page. This is Priya acting in PayPal, not SubGuard: it changes
    the mock PayPal state only. SubGuard learns about it the same way as in sandbox, by reading PayPal."""
    _mock_only(svc)
    sub = _own(svc, body.subscription_id, body.user_id, "paypal_autopay_cancel")
    if isinstance(sub, JSONResponse):
        return sub
    assert svc.gw.mock is not None
    try:
        await svc.gw.mock.cancel_subscription(sub.paypal_id, "Cancelled by the user in PayPal Automatic payments",
                                              request_id=f"autopay-{secrets.token_hex(4)}")
    except PayPalError as exc:
        return JSONResponse({"error": exc.message}, status_code=409)
    svc.store.audit.append(actor="user", event="paypal_autopay_cancel", user_id=body.user_id,
                           subscription_id=sub.id, transport="mock", status_before=sub.status,
                           status_after="CANCELLED", decision="n/a",
                           reason="Priya cancelled it herself on the (simulated) PayPal Automatic payments page")
    return {"ok": True, "status": "CANCELLED"}

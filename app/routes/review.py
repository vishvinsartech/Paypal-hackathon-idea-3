"""Fine-print review API. The companion calls /api/review/preflight before the PayPal approval (spec 5.5)."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.auditor import Auditor, save_review
from app.integrations.capture import CaptureError
from app.integrations.paypal_gateway import Ctx, PayPalGateway
from app.integrations.paypal_types import PayPalError
from app.models import Merchant, Review
from app.routes.deps import get_store
from app.routes.subscriptions import get_gateway
from app.store import JsonStore

router = APIRouter(prefix="/api")


class PreflightIn(BaseModel):
    merchant_url: str
    plan_id: str | None = None
    plan_key: str | None = None
    user_id: str = "priya"


def _resolve_plan(merchant: Merchant, gw: PayPalGateway, plan_key: str | None, plan_id: str | None) -> str:
    keys = [p.key for p in merchant.plans]
    if plan_key:
        if plan_key not in keys:
            raise HTTPException(404, "Unknown plan for this merchant")
        return plan_key
    if plan_id:
        for key in keys:
            try:
                if gw.plan_id(key) == plan_id:
                    return key
            except PayPalError:
                continue
        raise HTTPException(404, "Unknown plan id for this merchant")
    if not keys:
        raise HTTPException(404, "This merchant has no plans")
    return keys[0]


@router.post("/review/preflight", response_model=None)
async def preflight(body: PreflightIn, request: Request, store: JsonStore = Depends(get_store),
                    gw: PayPalGateway = Depends(get_gateway)) -> dict[str, Any] | JSONResponse:
    path = urlparse(body.merchant_url).path.rstrip("/")
    parts = path.split("/")
    if len(parts) < 3 or parts[1] != "shop":
        raise HTTPException(400, "SubGuard can only review the demo shop's merchant pages")
    merchant = next((mc for mc in store.load("merchants").items if mc.id == parts[2]), None)
    if merchant is None:
        raise HTTPException(404, "Unknown merchant")
    plan_key = _resolve_plan(merchant, gw, body.plan_key, body.plan_id)
    ctx = Ctx(actor="system", user_id=body.user_id, merchant=merchant)
    day = store.load("state").sim_day
    try:  # page capture (headless browser) and the PayPal plan fetch run side by side (D-119)
        capture, plan = await asyncio.gather(request.app.state.capture.capture(path, str(request.base_url)),
                                             gw.get_plan(gw.plan_id(plan_key), ctx))
    except CaptureError as exc:
        return JSONResponse({"error": "SubGuard couldn't read this page.", "detail": str(exc)}, status_code=502)
    auditor: Auditor = request.app.state.auditor
    data = await auditor.review(capture, plan, merchant=merchant, plan_key=plan_key, signup_day=day,
                                user_id=body.user_id)
    async with store.alocked():
        review = save_review(store, data, day)
    store.audit.append(
        actor="system", event="review_run", user_id=body.user_id, result=data.mode,
        reason=f"{merchant.name}: risk {data.risk_score}/100 ({data.mode_label})",
        details={"review_id": review.id, "merchant": merchant.id, "plan_id": plan.id, "risk": data.risk_score,
                 "types": data.types(), "capture": capture.method, "dropped_quotes": len(data.dropped_quotes),
                 "provider": data.provider, "model": data.model,
                 "deadline_day": data.deadlines.real_cancel_deadline_day})
    if data.injection_flagged:
        store.audit.append(actor="system", event="prompt_injection_flagged", user_id=body.user_id,
                           reason="Instructions aimed at AI found in merchant page; ignored, score unchanged",
                           details={"review_id": review.id, "merchant": merchant.id})
    return {"review_id": review.id, **data.model_dump(mode="json")}


@router.get("/reviews")
def list_reviews(merchant: str | None = None, subscription_id: str | None = None,
                 store: JsonStore = Depends(get_store)) -> list[Review]:
    return [r for r in store.load("reviews").items
            if (merchant is None or r.merchant_id == merchant)
            and (subscription_id is None or r.subscription_id == subscription_id)]


@router.get("/reviews/{review_id}")
def get_review(review_id: str, store: JsonStore = Depends(get_store)) -> Review:
    review = next((r for r in store.load("reviews").items if r.id == review_id), None)
    if review is None:
        raise HTTPException(404, "Unknown review")
    return review

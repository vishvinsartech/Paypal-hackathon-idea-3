"""Checkout + registration: the shop's PayPal button talks to these.

Mock mode: create -> mock-approve -> register. Sandbox: the PayPal JS SDK creates/approves, then onApprove
posts to /register. Register polls PayPal until ACTIVE (corner case 2) and only then saves the
subscription + consent snapshot. Unconfirmed subscriptions get no snapshot and no timer.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.services import Services
from app.core.signup import OwnershipError, register_active
from app.integrations.paypal_gateway import Ctx, PayPalGateway
from app.integrations.paypal_types import PayPalError, SubscriptionView
from app.models import Merchant, Subscription
from app.routes.deps import get_store
from app.store import JsonStore

router = APIRouter(prefix="/api")
POLL_INTERVAL = 3.0


def get_gateway(request: Request) -> PayPalGateway:
    return request.app.state.gateway


def _merchant(store: JsonStore, merchant_id: str) -> Merchant:
    merchant = next((mc for mc in store.load("merchants").items if mc.id == merchant_id), None)
    if merchant is None:
        raise HTTPException(404, "Unknown merchant")
    return merchant


def _check_user(store: JsonStore, user_id: str) -> None:
    if not any(u.id == user_id for u in store.load("users").items):
        raise HTTPException(404, "Unknown user")


class CheckoutIn(BaseModel):
    merchant_id: str
    plan_key: str
    user_id: str = "priya"


class ApproveIn(BaseModel):
    paypal_id: str


class RegisterIn(BaseModel):
    paypal_id: str
    merchant_id: str
    plan_key: str
    user_id: str = "priya"
    review_id: str | None = None  # the companion's preflight review, linked to the new subscription


@router.post("/checkout/create")
async def checkout_create(body: CheckoutIn, request: Request, store: JsonStore = Depends(get_store),
                          gw: PayPalGateway = Depends(get_gateway)) -> dict[str, Any]:
    merchant = _merchant(store, body.merchant_id)
    _check_user(store, body.user_id)
    if not any(p.key == body.plan_key for p in merchant.plans):
        raise HTTPException(404, "Unknown plan for this merchant")
    base = str(request.base_url).rstrip("/")
    view = await gw.create_subscription(
        gw.plan_id(body.plan_key), Ctx(actor="user", user_id=body.user_id, merchant=merchant),
        return_url=f"{base}/shop/{merchant.id}?approved=1", cancel_url=f"{base}/shop/{merchant.id}?cancelled=1")
    return {"paypal_id": view.id, "status": view.status, "approve_url": view.approve_url}


@router.post("/checkout/mock-approve")
async def checkout_mock_approve(body: ApproveIn, gw: PayPalGateway = Depends(get_gateway)) -> dict[str, Any]:
    if gw.mock is None:
        raise HTTPException(400, "Mock approval only exists in mock mode")
    view = await gw.mock_approve(body.paypal_id, Ctx(actor="user"))
    return {"paypal_id": view.id, "status": view.status}


async def _wait_active(gw: PayPalGateway, paypal_id: str, ctx: Ctx, timeout: float) -> SubscriptionView:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    view = await gw.get_subscription(paypal_id, ctx)
    while view.status in ("APPROVAL_PENDING", "APPROVED") and loop.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        view = await gw.get_subscription(paypal_id, ctx)
    return view


@router.post("/subscriptions/register", response_model=None)
async def register(body: RegisterIn, request: Request, store: JsonStore = Depends(get_store),
                   gw: PayPalGateway = Depends(get_gateway)) -> Subscription | JSONResponse:
    merchant = _merchant(store, body.merchant_id)
    _check_user(store, body.user_id)
    ctx = Ctx(actor="user", user_id=body.user_id, merchant=merchant)
    timeout = 60.0 if gw.mock is None else 0.0
    view = await _wait_active(gw, body.paypal_id, ctx, timeout)
    if view.status != "ACTIVE":
        store.audit.append(actor="system", event="subscription_register_pending", user_id=body.user_id,
                           reason=f"PayPal status is {view.status}; not registered (no timer, no snapshot)",
                           details={"paypal_id": body.paypal_id})
        return JSONResponse({"registered": False, "status": view.status}, status_code=202)

    svc: Services = request.app.state.services
    try:
        sub, _ = await register_active(svc, view, merchant_id=merchant.id, plan_key=body.plan_key,
                                       user_id=body.user_id, review_id=body.review_id)
    except OwnershipError as exc:
        raise HTTPException(409, str(exc)) from None
    return sub


@router.get("/subscriptions")
def list_subscriptions(user: str = "priya", store: JsonStore = Depends(get_store)) -> list[Subscription]:
    return [s for s in store.load("subscriptions").items if s.owner_id == user]


def paypal_error_response(exc: PayPalError) -> JSONResponse:
    msg = "PayPal couldn't complete that request. Please try again."
    if exc.name == "NOT_SEEDED":
        msg = exc.message
    return JSONResponse({"error": msg, "detail": exc.summary(), "debug_id": exc.debug_id}, status_code=502)

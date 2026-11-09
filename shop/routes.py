"""The dummy merchant website under /shop (fictional merchants only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import ROOT_DIR, Settings
from app.models import Merchant, UsageEvent
from app.routes.deps import get_settings, get_store
from app.store import JsonStore, utcnow

router = APIRouter(prefix="/shop")
templates = Jinja2Templates(directory=ROOT_DIR / "shop" / "templates")
PAGES = {"penwright": "penwright.html", "framewise": "framewise.html", "lumen": "lumen.html"}


def _merchant(store: JsonStore, merchant_id: str) -> Merchant:
    merchant = next((mc for mc in store.load("merchants").items if mc.id == merchant_id), None)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Unknown merchant")
    return merchant


def _render(request: Request, name: str, settings: Settings, **ctx: object) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"settings": settings, "p": settings.pricing, **ctx})


@router.get("", response_class=HTMLResponse)
def index(request: Request, settings: Settings = Depends(get_settings),
          store: JsonStore = Depends(get_store)) -> HTMLResponse:
    return _render(request, "index.html", settings, merchants=store.load("merchants").items)


@router.get("/penwright/terms", response_class=HTMLResponse)
def penwright_terms(request: Request, settings: Settings = Depends(get_settings),
                    store: JsonStore = Depends(get_store)) -> HTMLResponse:
    return _render(request, "penwright_tos.html", settings, merchant=_merchant(store, "penwright"))


@router.get("/{merchant_id}/app", response_class=HTMLResponse)
async def app_open(request: Request, merchant_id: str, user: str = "priya",
                   settings: Settings = Depends(get_settings),
                   store: JsonStore = Depends(get_store)) -> HTMLResponse:
    """Opening the fake app records a usage event for the current sim day."""
    merchant = _merchant(store, merchant_id)
    day = store.load("state").sim_day
    subs = store.load("subscriptions").items
    sub = next((s for s in subs if s.owner_id == user and s.merchant_id == merchant_id
                and s.addon_of is None and s.status == "ACTIVE"), None)
    async with store.aedit("usage") as usage:
        usage.items.append(UsageEvent(user_id=user, merchant_id=merchant_id,
                                      subscription_id=sub.id if sub else None, day=day, at=utcnow()))
        opens = sum(1 for e in usage.items if e.user_id == user and e.merchant_id == merchant_id)
    return _render(request, "app_open.html", settings, merchant=merchant, day=day, user=user, opens=opens)


@router.get("/{merchant_id}", response_class=HTMLResponse)
def merchant_page(request: Request, merchant_id: str, settings: Settings = Depends(get_settings),
                  store: JsonStore = Depends(get_store)) -> HTMLResponse:
    if merchant_id not in PAGES:
        raise HTTPException(status_code=404, detail="Unknown merchant")
    plan_ids = store.load("sandbox_ids").plans if settings.is_sandbox else {}
    return _render(request, PAGES[merchant_id], settings, merchant=_merchant(store, merchant_id), plan_ids=plan_ids)

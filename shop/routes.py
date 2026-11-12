"""The dummy merchant website under /shop (fictional merchants only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import session_user
from app.config import ROOT_DIR, Settings
from app.core.durations import number_words
from app.hosts import can_auto_approve, show_sandbox_buyer
from app.models import Merchant, UsageEvent
from app.routes.deps import get_settings, get_store
from app.store import JsonStore, utcnow

router = APIRouter(prefix="/shop")
templates = Jinja2Templates(directory=ROOT_DIR / "shop" / "templates")
PAGES = {"penwright": "penwright.html", "quillnote": "quillnote.html"}
TERMS_PAGES = {"penwright": "penwright_tos.html", "quillnote": "quillnote_tos.html"}


def _merchant(store: JsonStore, merchant_id: str) -> Merchant:
    merchant = next((mc for mc in store.load("merchants").items if mc.id == merchant_id), None)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Unknown merchant")
    return merchant


def _render(request: Request, name: str, settings: Settings, **ctx: object) -> HTMLResponse:
    """Shop pages are public (D-179); the session only decides Subscribe vs "Sign in to subscribe" + the chip."""
    user_id = session_user(request, settings)
    store: JsonStore = request.app.state.store
    me = next((u for u in store.load("users").items if u.id == user_id), None) if user_id else None
    return templates.TemplateResponse(request, name, {
        "settings": settings, "p": settings.pricing, "number_words": number_words,
        "auto_approve": can_auto_approve(settings, request),
        "signed_in": user_id is not None, "user_id": user_id or "", "user_name": me.name if me else (user_id or ""),
        **ctx})


@router.get("", response_class=HTMLResponse)
def index(request: Request, settings: Settings = Depends(get_settings),
          store: JsonStore = Depends(get_store)) -> HTMLResponse:
    return _render(request, "index.html", settings, merchants=store.load("merchants").items)


@router.get("/{merchant_id}/terms", response_class=HTMLResponse)
def merchant_terms(request: Request, merchant_id: str, settings: Settings = Depends(get_settings),
                   store: JsonStore = Depends(get_store)) -> HTMLResponse:
    if merchant_id not in TERMS_PAGES:
        raise HTTPException(status_code=404, detail="Unknown merchant")
    return _render(request, TERMS_PAGES[merchant_id], settings, merchant=_merchant(store, merchant_id))


async def _record(store: JsonStore, user: str, merchant_id: str, kind: str) -> tuple[int, int, int]:
    """Append one usage event for today; returns (day, opens, exports) for this user + merchant."""
    day = store.load("state").sim_day
    subs = store.load("subscriptions").items
    sub = next((s for s in subs if s.owner_id == user and s.merchant_id == merchant_id and s.status == "ACTIVE"),
               None)
    async with store.aedit("usage") as usage:
        usage.items.append(UsageEvent(user_id=user, merchant_id=merchant_id, kind=kind,  # type: ignore[arg-type]
                                      subscription_id=sub.id if sub else None, day=day, at=utcnow()))
        mine = [e for e in usage.items if e.user_id == user and e.merchant_id == merchant_id]
    return day, sum(1 for e in mine if e.kind == "open"), sum(1 for e in mine if e.kind == "export")


@router.get("/{merchant_id}/app", response_class=HTMLResponse)
async def app_open(request: Request, merchant_id: str, user: str = "priya",
                   settings: Settings = Depends(get_settings),
                   store: JsonStore = Depends(get_store)) -> HTMLResponse:
    """Opening the fake app records a usage event for the current sim day."""
    merchant = _merchant(store, merchant_id)
    day, opens, exported = await _record(store, user, merchant_id, "open")
    return _render(request, "app_open.html", settings, merchant=merchant, day=day, user=user, opens=opens,
                   exports=exported)


@router.post("/{merchant_id}/app/export", response_class=HTMLResponse)
async def app_export(request: Request, merchant_id: str, user: str = "priya",
                     settings: Settings = Depends(get_settings),
                     store: JsonStore = Depends(get_store)) -> HTMLResponse:
    """'Export a document' in the fake app: an export usage event (Penwright's early-trial-end trap, corner case 27)."""
    merchant = _merchant(store, merchant_id)
    day, opens, exported = await _record(store, user, merchant_id, "export")
    return _render(request, "app_open.html", settings, merchant=merchant, day=day, user=user, opens=opens,
                   exports=exported)


@router.get("/{merchant_id}", response_class=HTMLResponse)
def merchant_page(request: Request, merchant_id: str, settings: Settings = Depends(get_settings),
                  store: JsonStore = Depends(get_store)) -> HTMLResponse:
    if merchant_id not in PAGES:
        raise HTTPException(status_code=404, detail="Unknown merchant")
    plan_ids = store.load("sandbox_ids").plans if settings.is_sandbox else {}
    # D-192: the live demo's window on a server that can't approve for her: Priya approves in PayPal by hand. The
    # sandbox buyer's login is rendered into this page only (never an API, log or the audit log).
    manual_demo = (settings.is_sandbox and request.query_params.get("autodemo") == "1"
                   and not can_auto_approve(settings, request))
    buyer = ({"email": settings.paypal_sandbox_buyer_email, "password": settings.paypal_sandbox_buyer_password}
             if manual_demo and show_sandbox_buyer(settings) else None)
    return _render(request, PAGES[merchant_id], settings, merchant=_merchant(store, merchant_id), plan_ids=plan_ids,
                   manual_demo=manual_demo, sandbox_buyer=buyer)

"""Server-rendered SubGuard pages: the dashboard and the subscription detail page (spec 7.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import ROOT_DIR, Settings
from app.core import timers as tm
from app.core.savings import year_one_cost
from app.core.sub_dates import day_text, sub_act_by
from app.routes.actions import get_services
from app.routes.deps import get_settings, get_store
from app.store import JsonStore

router = APIRouter()
templates = Jinja2Templates(directory=ROOT_DIR / "app" / "templates")
AG_GRID_URL = "https://cdn.jsdelivr.net/npm/ag-grid-community@36.2.0/dist/ag-grid-community.min.js"
AG_CHARTS_URL = "https://cdn.jsdelivr.net/npm/ag-charts-community@14.2.0/dist/umd/ag-charts-community.min.js"  # D-108


def _base(request: Request, user: str, settings: Settings, store: JsonStore) -> dict[str, Any]:
    users = store.load("users").items
    current = next((u for u in users if u.id == user), users[0] if users else None)
    return {"settings": settings, "users": users, "current_user": current, "sim_day": store.load("state").sim_day,
            "ag_grid_url": AG_GRID_URL, "ag_charts_url": AG_CHARTS_URL, "llm": request.app.state.llm}


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request, user: str = "priya", demo: int = 0,
    settings: Settings = Depends(get_settings), store: JsonStore = Depends(get_store),
) -> HTMLResponse:
    ctx = _base(request, user, settings, store)
    ctx.update(demo=bool(demo), merchants=store.load("merchants").items, active_tab="demo")
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.get("/subscriptions/{sub_id}", response_class=HTMLResponse)
def subscription_page(
    request: Request, sub_id: str, user: str = "priya",
    settings: Settings = Depends(get_settings), store: JsonStore = Depends(get_store),
) -> HTMLResponse:
    svc = get_services(request)
    ctx = _base(request, user, settings, store)
    sub = svc.sub(sub_id)
    if sub is None or sub.owner_id != user:  # R5: only your own subscriptions
        return templates.TemplateResponse(request, "subscription.html", {**ctx, "sub": None}, status_code=404)
    merchant = svc.merchant(sub.merchant_id)
    review = tm.review_for(svc, sub)
    snap = sub.consent_snapshot
    notice = next((n for n in store.load("notices").items if n.subscription_id == sub.id), None)
    plans = [{"name": p.name, "year_one": svc.money(year_one_cost(p.billing_cycles))} for p in merchant.plans]
    d = review.data.deadlines if review else None
    ctx.update(act_by=sub_act_by(sub, d.real_cancel_deadline_day) if d else "",
               first_charge_on=day_text(sub, d.first_charge_day) if d else "")
    ctx.update(sub=sub, merchant=merchant, review=review, snap=snap, notice=notice, plans=plans,
               snap_year=svc.money(year_one_cost(snap.billing_cycles)) if snap else None, money=svc.money,
               evidence=sorted({c.evidence_testid for c in review.data.clauses if c.evidence_testid})
               if review else [])
    return templates.TemplateResponse(request, "subscription.html", ctx)

"""Server-rendered SubGuard pages: the dashboard and the subscription detail page (spec 7.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import ROOT_DIR, Settings
from app.core import timers as tm
from app.core.activity import activity_for, usage_by_day
from app.core.savings import money_protected, year_one_cost
from app.routes.actions import get_services
from app.routes.deps import get_settings, get_store
from app.store import JsonStore

router = APIRouter()
templates = Jinja2Templates(directory=ROOT_DIR / "app" / "templates")
AG_GRID_URL = "https://cdn.jsdelivr.net/npm/ag-grid-community@36.2.0/dist/ag-grid-community.min.js"


def _base(request: Request, user: str, settings: Settings, store: JsonStore) -> dict[str, Any]:
    users = store.load("users").items
    current = next((u for u in users if u.id == user), users[0] if users else None)
    return {"settings": settings, "users": users, "current_user": current, "sim_day": store.load("state").sim_day,
            "ag_grid_url": AG_GRID_URL, "llm": request.app.state.llm}


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
    ctx.update(sub=sub, merchant=merchant, review=review, snap=snap, notice=notice, plans=plans,
               snap_year=svc.money(year_one_cost(snap.billing_cycles)) if snap else None, money=svc.money,
               evidence=sorted({c.evidence_testid for c in review.data.clauses if c.evidence_testid})
               if review else [])
    return templates.TemplateResponse(request, "subscription.html", ctx)


@router.get("/user", response_class=HTMLResponse)
def user_dashboard(
    request: Request, user: str = "priya",
    settings: Settings = Depends(get_settings), store: JsonStore = Depends(get_store),
) -> HTMLResponse:
    """Priya's own view: what she signed up for, what she decided, what SubGuard and PayPal did (from the log)."""
    svc = get_services(request)
    ctx = _base(request, user, settings, store)
    subs = [s for s in store.load("subscriptions").items if s.owner_id == user]
    rows = []
    for s in subs:
        review = tm.review_for(svc, s)
        snap = s.consent_snapshot
        rows.append({"sub": s, "merchant": svc.merchant(s.merchant_id).name,
                     "risk": review.risk_score if review else None,
                     "deadline": review.data.deadlines.real_cancel_deadline_day if review else None,
                     "agreed": svc.money(snap.price) if snap else "—",
                     "year_one": svc.money(year_one_cost(snap.billing_cycles)) if snap else "—"})
    notices = [n for n in store.load("notices").items if n.subscription_id in {s.id for s in subs}]
    alerts = sorted((a for a in store.load("alerts").items if a.user_id == user), key=lambda a: a.created_at)
    protected = money_protected(subs, user, settings.pricing.demo_currency)
    activity = activity_for(svc, user)
    ctx.update(active_tab="user", rows=rows, notices=notices, alerts=alerts, activity=activity,
               usage=usage_by_day(svc, user), protected=svc.money(protected),
               cancelled=sum(1 for s in subs if s.status == "CANCELLED"),
               decisions=sum(1 for e in activity if e.who == "Priya"))
    return templates.TemplateResponse(request, "user.html", ctx)

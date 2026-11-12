"""Server-rendered SubGuard pages: the dashboard and the subscription detail page (spec 7.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import ROOT_DIR, Settings
from app.core import timers as tm
from app.core.activity import activity_for
from app.core.savings import year_one_cost
from app.core.sub_dates import day_text, sub_act_by
from app.core.verdict import verdict
from app.models import Subscription
from app.review_types import TYPE_LABELS, ReviewData
from app.routes.account_view import short_email
from app.routes.actions import get_services
from app.routes.deps import get_settings, get_store
from app.store import JsonStore

router = APIRouter()
SOURCE_LABELS = {"llm": "AI", "paypal_check": "PayPal", "code": "Code check", "rules": "Code check"}  # U24
templates = Jinja2Templates(directory=ROOT_DIR / "app" / "templates")
templates.env.filters["short_email"] = short_email  # "priya@…" in the avatar menu
AG_GRID_URL = "/static/vendor/ag-grid-community-36.2.0.min.js"  # U30: vendored, no CDN at runtime (D-108)
AG_CHARTS_URL = "/static/vendor/ag-charts-community-14.2.0.min.js"


def _base(request: Request, user: str, settings: Settings, store: JsonStore) -> dict[str, Any]:
    users = store.load("users").items
    current = next((u for u in users if u.id == user), users[0] if users else None)
    return {"settings": settings, "users": users, "current_user": current, "sim_day": store.load("state").sim_day,
            "ag_grid_url": AG_GRID_URL, "ag_charts_url": AG_CHARTS_URL, "llm": request.app.state.llm}


def signed_out_base(settings: Settings, store: JsonStore) -> dict[str, Any]:
    """base.html for a signed-out visitor (D-181): no user, so the top bar is brand, Demo shops and Sign in."""
    return {"settings": settings, "current_user": None, "signed_out": True, "sim_day": store.load("state").sim_day,
            "ag_grid_url": AG_GRID_URL}


def ai_vs_basic_view(sub: Subscription, data: ReviewData) -> dict[str, Any] | None:
    """A2: the side-by-side panel. Dates relative to the sign-up, like everywhere else (B2)."""
    cmp = data.ai_vs_basic()
    if cmp is None:
        return None

    def notice(n: int) -> str:
        return f"{n} day{'s' if n != 1 else ''}" if n else "not found"

    return {**cmp, "ai_act_by": day_text(sub, cmp["ai_act_by_day"]),
            "basic_act_by": day_text(sub, cmp["basic_act_by_day"]),
            "ai_notice": notice(cmp["ai_notice_days"]), "basic_notice": notice(cmp["basic_notice_days"]),
            "risky_labels": [TYPE_LABELS.get(t, t).lower() for t in cmp["ai_only_risky"]],
            "notice_quote": next((c.quote for c in data.clauses if c.type == "NOTICE_PERIOD"), None),
            "same": not cmp["ai_only"] and not cmp["basic_only"]
            and cmp["ai_notice_days"] == cmp["basic_notice_days"]}


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
    ctx.update(ai_vs_basic=ai_vs_basic_view(sub, review.data) if review else None, type_labels=TYPE_LABELS)
    if review:  # U14/U23: the same verdict the companion showed, from the agreed PayPal cycles
        cycles = snap.billing_cycles if snap else []
        first = day_text(sub, d.first_charge_day) if d else None
        ctx.update(verdict=verdict(cycles, svc.money, first, review.data.clauses, review.data.paypal_check),
                   findings=[{**c.model_dump(mode="json"), "label": TYPE_LABELS.get(c.type, c.type),
                              "source_label": SOURCE_LABELS.get(c.source, "Code check")} for c in review.data.clauses],
                   trial_end_on=day_text(sub, d.first_charge_day - 1) if d else "")
    acts = [a for a in activity_for(svc, user) if a.subscription_id == sub.id]
    ctx.update(acts=[{**a.model_dump(), "when": day_text(sub, a.day)} for a in reversed(acts)])
    ctx.update(sub=sub, merchant=merchant, review=review, snap=snap, notice=notice, plans=plans,
               snap_year=svc.money(year_one_cost(snap.billing_cycles)) if snap else None, money=svc.money,
               evidence=sorted({c.evidence_testid for c in review.data.clauses if c.evidence_testid})
               if review else [])
    return templates.TemplateResponse(request, "subscription.html", ctx)

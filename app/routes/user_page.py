"""Priya's SubGuard at `/`: the product view (FIX_PLAN U5, D-148). `/user` and `/me` redirect here.

Server-rendered: the subscription cards (with the check-in band and the Layer 2 handoff), the right column
(Charges avoided, Next decision, What SubGuard did), the Activity and Emails sections. `?demo=1` (or the D key)
shows the presenter bar. The page refreshes its `[data-live]` parts from this same HTML (home.js).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings
from app.core.activity import Activity, activity_for
from app.core.savings import charges_avoided, money_protected, year_one_cost
from app.core.services import Services
from app.core.sub_dates import day_text
from app.routes.actions import get_services
from app.routes.deps import get_settings, get_store
from app.routes.home_view import card, check_in, delivery_text, did_rows, handoffs, history_row, next_decision, proof
from app.routes.pages import _base, templates
from app.store import JsonStore

router = APIRouter()
DID_ROWS = 5  # U9: "What SubGuard did" shows the 5 latest meaningful events
GRID_AFTER = 5  # U10: the history grid only under "Show all" when there are more rows than this


def _subs(store: JsonStore, user: str) -> list[Any]:
    return [s for s in store.load("subscriptions").items if s.owner_id == user and s.status != "APPROVAL_PENDING"]


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request, user: str = "priya", demo: int = 0,
    settings: Settings = Depends(get_settings), store: JsonStore = Depends(get_store),
) -> HTMLResponse:
    svc = get_services(request)
    ctx = _base(request, user, settings, store)
    subs = sorted(_subs(store, user), key=lambda s: s.signup_day, reverse=True)
    notices = [n for n in store.load("notices").items if n.subscription_id in {s.id for s in subs}]
    alerts = sorted((a for a in store.load("alerts").items if a.user_id == user), key=lambda a: a.created_at)
    band = check_in(svc, alerts)
    hand = handoffs(svc, alerts, user)
    cards = [card(svc, s, band if band and band["subscription_id"] == s.id else None, hand.get(s.id)) for s in subs]
    acts = activity_for(svc, user)
    history = [history_row(c, [a for a in acts if a.subscription_id == c["id"]]) for c in cards]
    did = did_rows(svc, user)
    verify = store.audit.verify()

    def alert_when(a: Any) -> str:
        sub = svc.sub(a.subscription_id or "")
        return day_text(sub, a.sim_day) if sub else f"Day {a.sim_day}"

    ctx.update(demo=bool(demo), merchants=store.load("merchants").items, cards=cards, notices=notices,
               alerts=alerts, proof=proof(svc, alerts), next=next_decision(svc, cards), did=did[:DID_ROWS],
               did_all=did, history=history, grid_after=GRID_AFTER, delivery_text=delivery_text,
               chain_ok=verify.ok, alert_when=alert_when, chain_entries=verify.entries,
               protected=svc.money(money_protected(subs, user, settings.pricing.demo_currency)),
               avoided=svc.money(avoided := charges_avoided(subs, user, settings.pricing.demo_currency)),
               nothing_avoided=not avoided,  # before any cancel: show what's at stake, not "up to $0"
               at_stake=svc.money(sum((year_one_cost(s.consent_snapshot.billing_cycles) for s in subs
                                       if s.status == "ACTIVE" and s.kept_day is None and s.consent_snapshot),
                                      start=year_one_cost([]))),
               cancelled=sum(1 for s in subs if s.status == "CANCELLED"))
    return templates.TemplateResponse(request, "home.html", ctx)


@router.get("/user")
@router.get("/me")  # alias (FIX_PLAN persona)
def user_dashboard(request: Request) -> RedirectResponse:
    """The old dashboard URLs: same page now (U5). Keeps ?user=."""
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/{query}", status_code=307)


@router.get("/api/subscription-history")
def subscription_history(user: str = "priya", svc: Services = Depends(get_services)) -> list[dict[str, Any]]:
    """Priya's subscription history for the AG Grid (R5: only her subscriptions), newest first."""
    acts = activity_for(svc, user)
    rows = [history_row(card(svc, s), [a for a in acts if a.subscription_id == s.id]) for s in _subs(svc.store, user)]
    return sorted(rows, key=lambda r: r["signup_day"], reverse=True)


@router.get("/api/activity")
def activity(user: str = "priya", svc: Services = Depends(get_services)) -> list[Activity]:
    """Priya's timeline (from the audit log; R5: only her entries)."""
    return activity_for(svc, user)

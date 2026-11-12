"""Priya's SubGuard at `/`: the product view (FIX_PLAN U5, D-148). `/user` and `/me` redirect here.

Server-rendered: one story-state card per subscription (D-169: trial / check-in / cancelled / proof, plus kept and the
Layer 2 handoff), the right column (What SubGuard did), the Activity and Emails sections. `?demo=1` renders the Live
demo page instead (D-167: controls, the 7-step story, Priya's check-in, results), from the same context.
The page refreshes its `[data-live]` parts from this same HTML (home.js).
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
from app.core.timeline import by_day, date_label, timeline
from app.routes.actions import get_services
from app.routes.dashboard_view import dashboard_context
from app.routes.deps import get_settings, get_store
from app.routes.home_view import card, check_in, delivery_text, did_rows, handoffs, history_row, proof
from app.routes.landing import landing_view
from app.routes.pages import _base, templates
from app.routes.story_card import story
from app.store import JsonStore

router = APIRouter()
DID_ROWS = 5  # the Live demo page's "What SubGuard did" (demo.html) shows the 5 latest meaningful events
RECENT = 3  # D-172: the Overview's "What SubGuard did": the 3 latest Activity entries


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
    for c, s in zip(cards, subs, strict=True):
        c["story"] = story(svc, s, c, notices, alerts)  # D-169: the Overview's story-state card
    did = did_rows(svc, user)  # the Live demo page's list (demo.html)
    entries = timeline(svc, user)  # D-172: Activity and the Overview's "What SubGuard did" share this
    verify = store.audit.verify()

    def alert_when(a: Any) -> str:
        sub = svc.sub(a.subscription_id or "")
        return day_text(sub, a.sim_day) if sub else f"Day {a.sim_day}"

    merchants = store.load("merchants").items
    if not demo:  # D-174: the dashboard's sidebar sections
        ctx.update(dashboard_context(svc, user, subs, cards))
    if demo:  # D-173: the landing section above the controls, and the Quillnote "connected" toggle's state
        ctx.update(landing=landing_view(settings),
                   quillnote_connected=any(m.id == "quillnote" and m.fair_trial_member for m in merchants))
    ctx.update(demo=bool(demo), merchants=merchants, cards=cards, notices=notices,
               alerts=alerts, proof=proof(svc, alerts), did=did[:DID_ROWS], delivery_text=delivery_text,
               days=by_day(svc, entries), recent=[(date_label(svc, e.day), e) for e in entries[:RECENT]],
               asks=sum(1 for e in entries if e.mark == "ask"),
               chain_ok=verify.ok, alert_when=alert_when, chain_entries=verify.entries,
               protected=svc.money(money_protected(subs, user, settings.pricing.demo_currency)),
               avoided=svc.money(avoided := charges_avoided(subs, user, settings.pricing.demo_currency)),
               nothing_avoided=not avoided,  # before any cancel: show what's at stake, not "up to $0"
               at_stake=svc.money(sum((year_one_cost(s.consent_snapshot.billing_cycles) for s in subs
                                       if s.status == "ACTIVE" and s.kept_day is None and s.consent_snapshot),
                                      start=year_one_cost([]))),
               cancelled=sum(1 for s in subs if s.status == "CANCELLED"))
    return templates.TemplateResponse(request, "demo.html" if demo else "home.html", ctx)


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

"""userA's dashboard (/user): the product, written to her (D-110, D-111).

Server-rendered parts: subscription cards, the Day 5 check-in (usage + advice + Keep / Cancel), the Day 11 proof,
money KPIs, messages and emails. AG Grid (subscription history, D-118) and AG Charts load from
/api/subscription-history and /api/analytics.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.config import Settings
from app.core import timers as tm
from app.core.activity import Activity, activity_for
from app.core.savings import money_protected, year_one_cost
from app.core.services import Services
from app.core.sub_dates import key_dates, stamp
from app.core.usage import last_open_day, opens_between, times
from app.models import Alert, Subscription
from app.routes.actions import get_services
from app.routes.deps import get_settings, get_store
from app.routes.pages import _base, templates
from app.routes.views import current_timer, sub_view
from app.store import JsonStore

router = APIRouter()
RARELY_USED = 3  # fewer opens than this during the trial -> SubGuard suggests cancelling (advice only, D-111)


def card(svc: Services, sub: Subscription) -> dict[str, Any]:
    """One subscription card: the grid row's facts plus the site-vs-real deadline line."""
    timers = svc.store.load("timers").items
    view = sub_view(svc, sub, timers)
    review = tm.review_for(svc, sub)
    deadline = review.data.deadlines.real_cancel_deadline_day if review else view["deadline_day"]
    dates = key_dates(svc, sub, view, current_timer(timers, sub.id), deadline)
    next_charge = view["next_charge_text"]
    if sub.status != "ACTIVE" and sub.next_billing_day is not None:
        next_charge = f"Day {sub.next_billing_day} · blocked (no active PayPal subscription)"
    return {**view, "deadline_day": deadline, "next_charge_text": next_charge, "dates": dates,
            "subscribed": stamp(sub.registered_at, with_time=True),
            "dated": {r["key"]: r["when"] for r in dates}, "can_decide": sub.status == "ACTIVE"
            and sub.kept_day is None, "risk_level": "high" if (view["risk"] or 0) >= 60 else
            ("mid" if (view["risk"] or 0) >= 30 else "low")}


def check_in(svc: Services, alerts: list[Alert]) -> dict[str, Any] | None:
    """The open Day 5 "keep or cancel?" alert, with usage numbers and SubGuard's advice (code, not the LLM)."""
    alert = next((a for a in reversed(alerts) if a.kind == "reminder" and a.acknowledged_at is None), None)
    sub = svc.sub(alert.subscription_id or "") if alert else None
    if alert is None or sub is None or sub.status != "ACTIVE":
        return None
    merchant = svc.merchant(sub.merchant_id)
    opens = opens_between(svc.store, sub.owner_id, sub.merchant_id, sub.signup_day, svc.day)
    last = last_open_day(svc.store, sub.owner_id, sub.merchant_id, svc.day)
    days = max(1, svc.day - sub.signup_day)
    cost = year_one_cost(sub.consent_snapshot.billing_cycles) if sub.consent_snapshot else None
    suggest = "cancel" if opens < RARELY_USED else "keep"
    used = f"You opened it {times(opens)} in {days} days" if opens else f"You haven't opened it in {days} days"
    reason = used + (f", and keeping it costs {svc.money(cost)} in the first paid year." if cost else ".")
    return {"alert": alert, "merchant": merchant.name,
            "usage": (f"Opened {times(opens)} in {days} days" if opens else f"Not opened in {days} days")
            + (f" (last on Day {last})." if last is not None else "."),
            "suggest": suggest, "reason": reason}


def proof(svc: Services, alerts: list[Alert]) -> str | None:
    """The Day 11 proof: the first charge was due and found no active PayPal subscription."""
    blocked = next((a for a in reversed(alerts) if a.kind == "blocked_charge"), None)
    if blocked is None:
        return None
    if blocked.sim_day == svc.day:
        return blocked.body  # "First charge due today: blocked. No active PayPal subscription."
    return f"Day {blocked.sim_day}: first charge blocked. No active PayPal subscription."


@router.get("/user", response_class=HTMLResponse)
def user_dashboard(
    request: Request, user: str = "usera",
    settings: Settings = Depends(get_settings), store: JsonStore = Depends(get_store),
) -> HTMLResponse:
    svc = get_services(request)
    ctx = _base(request, user, settings, store)
    subs = [s for s in store.load("subscriptions").items if s.owner_id == user and s.status != "APPROVAL_PENDING"]
    notices = [n for n in store.load("notices").items if n.subscription_id in {s.id for s in subs}]
    alerts = sorted((a for a in store.load("alerts").items if a.user_id == user), key=lambda a: a.created_at)
    ctx.update(active_tab="user", cards=[card(svc, s) for s in subs], notices=notices, alerts=alerts,
               check_in=check_in(svc, alerts), proof=proof(svc, alerts),
               protected=svc.money(money_protected(subs, user, settings.pricing.demo_currency)),
               cancelled=sum(1 for s in subs if s.status == "CANCELLED"))
    return templates.TemplateResponse(request, "user.html", ctx)


def outcome(c: dict[str, Any]) -> str:
    """The card's Status line, as one grid cell."""
    if c["cancelled_day"] is not None:
        by = {"user": "by you", "timer": "by your safety timer"}.get(c["cancelled_by"] or "", "outside SubGuard")
        return f"Cancelled in PayPal on Day {c['cancelled_day']} {by}"
    if c["kept_day"] is not None:
        return f"You kept it on Day {c['kept_day']}"
    return "Watching for you"


def history_row(c: dict[str, Any], acts: list[Activity]) -> dict[str, Any]:
    """One row of the subscription history grid: the card's facts + its events from the audit log."""
    iso = {k: (w["iso"] if w else None) for k, w in c["dated"].items()}
    return {"id": c["id"], "merchant": c["merchant"], "plan": c["plan"], "price": c["price_text"],
            "status": c["status"], "risk": c["risk"], "signup_day": c["signup_day"],
            "subscribed_at": iso.get("subscribed"), "trial_end_day": c["trial_end_day"],
            "trial_end_at": iso.get("trial_end"), "deadline_day": c["deadline_day"],
            "deadline_at": iso.get("deadline"), "next_charge": c["next_charge_text"],
            "timer": c["timer_text"] or "—", "outcome": outcome(c), "events": len(acts),
            "last_event": f"Day {acts[-1].day} · {acts[-1].text}" if acts else "",
            "event_log": [f"Day {a.day} · {a.who}: {a.text}" for a in acts]}


@router.get("/api/subscription-history")
def subscription_history(user: str = "usera", svc: Services = Depends(get_services)) -> list[dict[str, Any]]:
    """userA's subscription history for the AG Grid (R5: only her subscriptions), newest first."""
    subs = [s for s in svc.store.load("subscriptions").items if s.owner_id == user and s.status != "APPROVAL_PENDING"]
    acts = activity_for(svc, user)
    rows = [history_row(card(svc, s), [a for a in acts if a.subscription_id == s.id]) for s in subs]
    return sorted(rows, key=lambda r: r["signup_day"], reverse=True)


@router.get("/api/activity")
def activity(user: str = "usera", svc: Services = Depends(get_services)) -> list[Activity]:
    """userA's timeline for the AG Grid activity list (from the audit log; R5: only her entries)."""
    return activity_for(svc, user)

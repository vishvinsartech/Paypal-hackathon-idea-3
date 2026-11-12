"""View models for Priya's SubGuard at `/` (FIX_PLAN Phase 3, U5-U12; D-148).

One merged card per subscription (U7): merchant · plan, status, risk; a big cost line; the act-by line; the five
dots; one pair of actions; a quiet "Verified with PayPal" footer. On the check-in day the card's top becomes the
"Keep it or cancel?" band and its buttons become that decision (U8). A Layer 2 handoff takes the card's place for
actions (A5). The Overview renders each card as a story state (story_card.py, D-169). All text from code.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core import timers as tm
from app.core.activity import Activity, activity_for
from app.core.layer2 import open_handoffs
from app.core.savings import year_one_cost
from app.core.services import Services
from app.core.sub_dates import day_text, key_dates, signup_moment, stamp, sub_act_by
from app.core.usage import SIMULATED_SOURCE, last_open_day, opens_between, times
from app.core.verdict import cost_facts, cost_line, sub_line
from app.integrations.paypal_types import first_paid_price
from app.models import Alert, Subscription
from app.routes.views import current_timer, sub_view

RARELY_USED = 3  # fewer opens than this during the trial -> SubGuard suggests cancelling (advice only, D-111)
DELIVERY = {"in_app": "App", "email": "Email", "sms": "SMS"}
DELIVERED = {"shown", "accepted", "mocked", "sent", "ok"}
NOT_DONE = ("You asked the SubGuard chat",)  # U9: left out of "What SubGuard did"


def delivery_text(delivery: dict[str, str]) -> str:
    """U4: "App ✓ · Email ✓ · SMS ✓" instead of "in_app: shown · email: mocked · sms: mocked"."""
    return " · ".join(f"{DELIVERY.get(k, k)} {'✓' if v in DELIVERED else '✗'}" for k, v in delivery.items())


def outcome(svc: Services, sub: Subscription) -> str:
    """The card's status line, with calendar dates."""
    if sub.cancelled_day is not None:
        by = {"user": "by you", "timer": "by your safety timer"}.get(sub.cancelled_by or "", "outside SubGuard")
        return f"Cancelled in PayPal on {day_text(sub, sub.cancelled_day)} {by}"
    if sub.kept_day is not None:
        return f"You kept it on {day_text(sub, sub.kept_day)}"
    return "Watching for you"


def check_in(svc: Services, alerts: list[Alert]) -> dict[str, Any] | None:
    """The open "keep or cancel?" alert, with usage numbers and SubGuard's advice (code, not the LLM)."""
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
    source = SIMULATED_SOURCE.format(name=tm.short(merchant.name))  # D8: say where the usage numbers come from
    return {"alert": alert, "subscription_id": sub.id, "merchant": merchant.name, "used": used,
            "usage": (f"Opened {times(opens)} in {days} days" if opens else f"Not opened in {days} days")
            + (f", last on {day_text(sub, last)} ({source})" if opens and last is not None else "") + ".",
            "suggest": suggest, "reason": reason}


def proof(svc: Services, alerts: list[Alert]) -> str | None:
    """The Day 11 proof: the first charge was due and found no active PayPal subscription."""
    blocked = next((a for a in reversed(alerts) if a.kind == "blocked_charge"), None)
    if blocked is None:
        return None
    if blocked.sim_day == svc.day:
        return f"First charge due today. {blocked.body}"
    sub = svc.sub(blocked.subscription_id or "")
    when = day_text(sub, blocked.sim_day) if sub else f"Day {blocked.sim_day}"
    return f"First charge was due {when}. {blocked.body}"


def handoffs(svc: Services, alerts: list[Alert], user: str) -> dict[str, dict[str, Any]]:
    """A5: open Layer 2 handoffs by subscription id: one-tap PayPal link, the email draft, SubGuard watching."""
    out: dict[str, dict[str, Any]] = {}
    for a in open_handoffs(alerts, user):
        notice = next((x.get("notice_id") for x in a.actions if x["action"] == "review_email"), None)
        sub = svc.sub(a.subscription_id or "")
        if sub is not None and sub.id not in out:
            out[sub.id] = {"alert": a, "merchant": svc.merchant(sub.merchant_id).name, "notice_id": notice,
                           "url": svc.settings.autopay_link}
    return out


def card(svc: Services, sub: Subscription, band: dict[str, Any] | None = None,
         handoff: dict[str, Any] | None = None) -> dict[str, Any]:
    timers = svc.store.load("timers").items
    view = sub_view(svc, sub, timers)
    review = tm.review_for(svc, sub)
    deadline = review.data.deadlines.real_cancel_deadline_day if review else view["deadline_day"]
    dates = key_dates(svc, sub, view, current_timer(timers, sub.id), deadline)
    snap = sub.consent_snapshot
    cycles = snap.billing_cycles if snap else []
    first = sub.next_billing_day
    first_text = day_text(sub, first) if first is not None else None
    active = sub.status == "ACTIVE"
    if active:
        cost = cost_line(cycles, svc.money, first_text) if cycles else view["price_text"]
    elif cycles and first is not None and sub.cancelled_day is not None and sub.cancelled_day < first:
        cost = f"Cancelled. You won't be charged {svc.money(first_paid_price(cycles))} on {first_text}."
    else:
        cost = "Cancelled in PayPal." if sub.status == "CANCELLED" else sub.status.title()
    next_charge = view["next_charge_text"]
    if not active and first is not None:
        next_charge = f"{first_text} · blocked (no active PayPal subscription)"
    can_decide = active and sub.kept_day is None and handoff is None
    level = "high" if (view["risk"] or 0) >= 60 else ("mid" if (view["risk"] or 0) >= 30 else "low")
    trial_end_text = day_text(sub, view["trial_end_day"]) if view.get("trial_end_day") is not None else ""
    show_act_by = can_decide and deadline is not None and svc.day <= deadline
    facts = cost_facts(cycles, svc.money, first_text, trial_end_text) if active else []
    if not active and cycles and first is not None and sub.cancelled_day is not None and sub.cancelled_day < first:
        facts = [{"key": "next", "label": f"Charge on {first_text}", "value": svc.money(Decimal("0")),
                  "note": f"{svc.money(first_paid_price(cycles))} blocked in PayPal", "tone": "ok"}]
    return {**view, "deadline_day": deadline, "next_charge_text": next_charge, "dated": {r["key"]: r["when"]
            for r in dates}, "cost_line": cost, "cost_sub": sub_line(cycles, svc.money) if cycles and active
            and sub.kept_day is None else "", "act_by_text": sub_act_by(sub, deadline) if deadline is not None
            else "", "trial_end_text": trial_end_text, "subscribed": stamp(signup_moment(sub), with_time=True),
            "can_decide": can_decide, "show_act_by": show_act_by, "risk_level": level, "facts": facts,
            "headline": headline(sub, band, handoff, deadline if show_act_by else None, first_text),
            "band": band, "handoff": handoff, "outcome": outcome(svc, sub),
            "kept": sub.kept_day is not None, "cancelled": sub.status == "CANCELLED"}


def headline(sub: Subscription, band: dict[str, Any] | None, handoff: dict[str, Any] | None,
             act_by: int | None, first_text: str | None) -> dict[str, str]:
    """The one phrase on the collapsed row: what matters about this subscription right now."""
    if handoff:
        return {"text": "Action needed: cancel in PayPal", "tone": "urgent"}
    if band:
        return {"text": "Check-in: keep it or cancel?", "tone": "warn"}
    if act_by is not None:
        return {"text": f"Act by {day_text(sub, act_by)}", "tone": "urgent"}
    if sub.cancelled_day is not None:
        return {"text": f"Cancelled {day_text(sub, sub.cancelled_day)}" + (
            " · no charge" if sub.next_billing_day is not None and sub.cancelled_day < sub.next_billing_day
            else ""), "tone": "ok"}
    if sub.kept_day is not None:
        return {"text": f"Kept · first charge {first_text}" if first_text else "Kept", "tone": "muted"}
    return {"text": "Watching for you", "tone": "muted"}


def did_rows(svc: Services, user: str) -> list[dict[str, Any]]:
    """Priya's meaningful events, newest first, with a calendar date per row (U9 shows the first 5)."""
    mine = sorted((s for s in svc.store.load("subscriptions").items if s.owner_id == user and s.registered_at),
                  key=lambda s: s.registered_at or 0)
    rows = []
    for a in reversed(activity_for(svc, user)):
        if a.text.startswith(NOT_DONE):  # her own chat questions aren't something SubGuard did
            continue
        # entries without a subscription (a review before sign-up) are dated from her latest sign-up's clock
        sub = svc.sub(a.subscription_id or "") or (mine[-1] if mine else None)
        rows.append({**a.model_dump(), "when": day_text(sub, a.day) if sub else f"Day {a.day}"})
    return rows


def history_row(c: dict[str, Any], acts: list[Activity]) -> dict[str, Any]:
    """One row of the subscription history (Activity list + the AG Grid under "Show all")."""
    iso = {k: (w["iso"] if w else None) for k, w in c["dated"].items()}
    return {"id": c["id"], "merchant": c["merchant"], "plan": c["plan"], "price": c["price_text"],
            "status": c["status"], "risk": c["risk"], "signup_day": c["signup_day"],
            "subscribed_at": iso.get("subscribed"), "trial_end_day": c["trial_end_day"],
            "trial_end_at": iso.get("trial_end"), "deadline_day": c["deadline_day"],
            "deadline_at": iso.get("deadline"), "next_charge": c["next_charge_text"],
            "timer": c["timer_text"] or "—", "outcome": c["outcome"], "events": len(acts),
            "last_event": acts[-1].text if acts else "",
            "event_log": [f"Day {a.day} · {a.who}: {a.text}" for a in acts]}

"""Priya's Overview card as one story state (D-169).

Each subscription card shows one headline, one sub-line, at most two buttons and a timeline, for the state it is in:
trial -> check-in -> cancelled -> proof (plus kept and the Layer 2 handoff). Text and numbers come from code (R7);
every date is a calendar date (B2). The card never repeats itself: the headline, the sub-line and the timeline each
say something the others don't.

    trial      "Free until Nov 21, then $24.99/month"   Up to $524.88 this year if you keep it.
    check-in   "Keep your Penwright trial?"              usage · advice · when the safety timer acts
    cancelled  "You won't be charged"                    $24.99 saved now · up to $524.88 this year
    proof      "$24.99 never charged"                    what PayPal showed · up to $524.88 saved this year

Under the headline, "My plan" says what SubGuard will do next, from the timer and Settings (D-177).
"""

from __future__ import annotations

from typing import Any

from app.core.savings import year_one_cost
from app.core.services import Services
from app.core.sub_dates import day_text
from app.core.verdict import UNIT
from app.integrations.paypal_types import first_paid_price
from app.models import Alert, Notice, Subscription, Timer
from app.routes.views import current_timer

# Merchant tiles: coloured initials (white text, each colour >= 4.5:1 against white).
TILE_COLOURS = ("#6a4fd8", "#b4532a", "#1f6fb2", "#a8336b", "#2e7d55", "#7a5a12")
TILE_LABELS = {"Penwright Studio": "Pw"}  # D-177: not "PS", which reads like Priya's "P" avatar


def initials(name: str) -> str:
    if name in TILE_LABELS:
        return TILE_LABELS[name]
    words = [w for w in name.split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or name[:1].upper()


def tile_colour(merchant_id: str) -> str:
    return TILE_COLOURS[sum(map(ord, merchant_id)) % len(TILE_COLOURS)]


def _node(key: str, label: str, day: int | None, sub: Subscription, state: str, mark: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "day": day, "date": day_text(sub, day) if day is not None else "",
            "state": state, "mark": mark, "is_key": False}


def timeline(sub: Subscription, today: int, *, reminder: int | None, act_by: int | None,
             notice: Notice | None, auto_day: int | None = None) -> dict[str, Any]:
    """Signed up ✓ -> Checked in ✓ -> Cancelled ✓ -> Email sent ✓ -> First charge ✗ blocked (the cancel path), or
    Signed up ✓ -> Check-in -> Auto-cancel (if no answer; only when it's on) -> Act by -> First charge while the trial
    runs. Nodes are evenly spaced; the "Today" pin sits between them by date."""
    nodes = [_node("signup", "Signed up", sub.signup_day, sub, "done", "✓")]
    end = sub.cancelled_day if sub.cancelled_day is not None else sub.kept_day
    if reminder is not None and (end is None or reminder <= end):
        done = reminder <= today
        nodes.append(_node("check_in", "Checked in" if done else "Check-in", reminder, sub,
                           "done" if done else "next", "✓" if done else ""))
    first = sub.next_billing_day
    if sub.cancelled_day is not None:
        label = "Auto-cancelled" if sub.cancelled_by == "timer" else "Cancelled"
        nodes.append(_node("cancelled", label, sub.cancelled_day, sub, "done", "✓"))
        if notice is not None and notice.status == "sent":
            nodes.append(_node("email", "Email sent", notice.sim_day, sub, "done", "✓"))
        elif notice is not None:
            nodes.append(_node("email", "Email to send", None, sub, "next"))
        if first is not None and sub.cancelled_day < first:
            nodes.append(_node("first_charge", "First charge", first, sub, "blocked", "✗"))
            nodes[-1]["note"] = "blocked"
        key = "first_charge" if first is not None and today >= first and nodes[-1]["key"] == "first_charge" \
            else "cancelled"
    elif sub.kept_day is not None:
        nodes.append(_node("kept", "Kept", sub.kept_day, sub, "done", "✓"))
        if first is not None:
            nodes.append(_node("first_charge", "First charge", first, sub, "done" if today >= first else "next",
                               "✓" if today >= first else ""))
        key = "kept"
    else:
        if auto_day is not None:
            nodes.append(_node("auto_cancel", "Auto‑cancel", auto_day, sub, "next"))
            nodes[-1]["note"] = "if no answer"
        if act_by is not None:
            nodes.append(_node("act_by", "Act by", act_by, sub, "done" if act_by < today else "next"))
        if first is not None:
            nodes.append(_node("first_charge", "First charge", first, sub, "next"))
        key = "act_by"
    for n in nodes:
        n["is_key"] = n["key"] == key
    n_count = len(nodes)
    centres = [(i + 0.5) / n_count * 100 for i in range(n_count)]
    for n, c in zip(nodes, centres, strict=True):
        n["pos"] = round(c, 2)
    return {"nodes": nodes, "today_pos": _today_pos(nodes, centres, today),
            "line": (round(centres[0], 2), round(100 - centres[-1], 2))}


def _today_pos(nodes: list[dict[str, Any]], centres: list[float], today: int) -> float:
    """Interpolate today between the dated nodes around it (undated nodes, like "Email to send", are skipped)."""
    dated = [(n["day"], c) for n, c in zip(nodes, centres, strict=True) if n["day"] is not None]
    on_day = [c for d, c in dated if d == today]
    if on_day:
        return round(max(on_day), 2)
    before = [(d, c) for d, c in dated if d < today]
    after = [(d, c) for d, c in dated if d > today]
    if not before:
        return round(dated[0][1], 2)
    if not after:
        return round(dated[-1][1], 2)
    (d0, c0), (d1, c1) = before[-1], after[0]
    return round(c0 + (c1 - c0) * (today - d0) / (d1 - d0), 2)


def my_plan(svc: Services, sub: Subscription, state: str, timer: Timer | None, *,
            fair_trial: bool) -> dict[str, Any] | None:
    """What SubGuard will do next, in its own voice, only what the code really does (R7): the check-in, then the
    timer (Settings on; Layer 2 hands over instead of cancelling) or a second reminder on the Act by day (off)."""
    if state == "kept":
        return {"text": "You chose to keep it. I'll stop asking.", "pending": False, "auto": False}
    if sub.status == "CANCELLED" and sub.cancelled_day is not None:
        return {"text": f"Cancelled in PayPal on {day_text(sub, sub.cancelled_day)}.", "pending": False, "auto": False}
    if state not in ("trial", "checkin") or timer is None or timer.kind != "trial" or timer.status != "PENDING" \
            or timer.reminder_day is None or timer.deadline_day is None:
        return None
    owner = svc.user(sub.owner_id)
    auto = (owner is None or owner.settings.auto_cancel_trials) and not sub.essential  # R2 + R6
    check = day_text(sub, timer.reminder_day)
    past = timer.reminder_day <= svc.day
    said = f"I checked in with you on {check}" if past else f"I'll check in with you on {check}"
    act_by = day_text(sub, timer.deadline_day)
    if not auto:
        return {"text": f"{said} and remind you again on {act_by}. I won't cancel without you.", "pending": True,
                "auto": False}
    gap = timer.deadline_day - timer.fire_day
    before = "a day" if gap == 1 else f"{gap} days"
    fire = day_text(sub, timer.fire_day)
    then = (f"I'll cancel it in PayPal on {fire}" if fair_trial
            else f"On {fire} I'll draft your cancellation email and send you a one-tap PayPal link")
    return {"text": f"{said}. No answer? {then}, {before} before your {act_by} deadline.", "pending": True,
            "auto": True}


def story(svc: Services, sub: Subscription, c: dict[str, Any], notices: list[Notice],
          alerts: list[Alert]) -> dict[str, Any]:
    """The story state of one card: state, headline, sub-line, buttons, timeline, risk badge, tile."""
    cycles = sub.consent_snapshot.billing_cycles if sub.consent_snapshot else []
    paid = [x for x in cycles if x.price > 0]
    price = f"{svc.money(paid[0].price)}/{UNIT[paid[0].interval_unit]}" if paid else c["price_text"]
    first_amount = svc.money(first_paid_price(cycles)) if paid else ""
    year = svc.money(year_one_cost(cycles)) if paid else ""
    short = c["merchant"].split()[0]
    notice = next((n for n in reversed(notices) if n.subscription_id == sub.id), None)
    draft = notice if notice is not None and notice.status == "draft" else None
    proven = any(a.kind == "blocked_charge" and a.subscription_id == sub.id for a in alerts)
    timer = current_timer(svc.store.load("timers").items, sub.id)
    act_by = c["deadline_day"] if c["can_decide"] else None
    band, hand = c["band"], c["handoff"]
    buttons: list[dict[str, Any]] = []
    head_key, head = "", ""
    sub_key, sub_line, sub_parts = "", "", []
    first = sub.next_billing_day
    blocked = sub.cancelled_day is not None and first is not None and sub.cancelled_day < first
    if hand:
        state, head = "handoff", hand["alert"].title
        sub_line = f"SubGuard checks PayPal every few seconds and updates this card when {short} shows CANCELLED."
        buttons.append({"kind": "link", "label": "Open PayPal Automatic payments ↗", "href": hand["url"],
                        "testid": "action-autopay", "main": True})
        if hand["notice_id"]:
            buttons.append({"kind": "email", "label": "Review email", "notice": hand["notice_id"],
                            "testid": "action-review-email"})
    elif band:
        state, head = "checkin", f"Keep your {short} trial?"
        advice = "cancelling" if band["suggest"] == "cancel" else "keeping it"
        sub_parts = [("reminder-usage", band["used"] + "."),
                     ("reminder-advice", f"SubGuard suggests {advice}; you decide.")]
        pair = [{"kind": "alert", "action": "cancel", "label": "Cancel trial", "testid": "alert-cancel"},
                {"kind": "alert", "action": "keep", "label": "Keep", "testid": "alert-keep"}]
        if band["suggest"] != "cancel":
            pair.reverse()
        pair[0]["main"] = True
        buttons = [{**b, "alert": band["alert"].id} for b in pair]
    elif sub.status == "CANCELLED" and blocked and proven:
        state, head_key, head = "proof", first_amount, " never charged"
        sub_line = f"PayPal had no active subscription to charge · up to {year} saved this year"
    elif sub.status == "CANCELLED" and blocked:
        state, head = "cancelled", "You won't be charged"
        sub_key, sub_line = first_amount, f" saved now · up to {year} this year"
    elif sub.status == "CANCELLED":
        state, head = "cancelled", "Cancelled in PayPal"
    elif sub.kept_day is not None:
        state, head = "kept", f"You're keeping {short}"
        sub_line = f"{price} after the trial · up to {year} this year. SubGuard won't ask again."
    else:
        state = "trial"
        trial_end = c["trial_end_text"]
        head = f"Free until {trial_end}, then {price}" if trial_end else price
        # the terms' own last day is on See evidence (D-177); the card keeps one line
        sub_line = f"Up to {year} this year if you keep it." if year else ""
        if c["can_decide"]:
            buttons = [{"kind": "sub", "action": "cancel", "label": "Cancel trial", "testid": "sub-cancel",
                        "main": True},
                       {"kind": "sub", "action": "keep", "label": "Keep", "testid": "sub-keep"}]
    if draft is not None and state in ("cancelled", "proof"):
        buttons = [{"kind": "email", "label": "Review & send email", "notice": draft.id, "testid": "email-review",
                    "main": True}]
    plan = my_plan(svc, sub, state, timer, fair_trial=c["fair_trial"])
    risk = c["risk"]
    if risk is None:
        badge = None
    elif sub.status == "CANCELLED":
        badge = {"text": f"Risk was {risk}", "tone": "was"}
    else:
        badge = {"text": f"Risk {risk}/100", "tone": c["risk_level"]}
    return {"state": state, "head": head, "head_key": head_key, "sub_line": sub_line, "sub_key": sub_key,
            "sub_parts": [p for p in sub_parts if p[1]], "buttons": buttons[:2], "badge": badge,
            "initials": initials(c["merchant"]), "tile": tile_colour(c["merchant_id"]),
            "plan": plan,
            "timeline": timeline(sub, svc.day, reminder=timer.reminder_day if timer else None, act_by=act_by,
                                 notice=notice, auto_day=timer.fire_day if plan and plan["auto"] else None),
            "new_trial": sub.status == "CANCELLED", "short": short,
            # the card is a dropdown; it opens by itself only when Priya has something to do (D-170)
            "open": state in ("checkin", "handoff") or any(b["kind"] == "email" and b.get("main") for b in buttons)}

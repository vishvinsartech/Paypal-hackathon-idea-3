"""Priya's dashboard sections (D-174): the Subscriptions list, Overview's "Coming up" and "Saved so far", and the
Analytics charts. Two sources, always labelled: the live run (Penwright, Quillnote: real PayPal Sandbox subscriptions,
or the simulated PayPal in mock mode) and the read-only sample history (sample_history.py). Money from code, Decimal.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.core.analytics import first_year_charges
from app.core.sample_history import SampleSub, samples
from app.core.savings import charges_avoided
from app.core.services import Services
from app.core.sub_dates import cal, date_of_day
from app.core.timeline_types import run_day0
from app.core.usage import last_open_day
from app.integrations.paypal_types import cycle_days, first_paid_price
from app.models import Subscription
from app.routes.home_view import outcome
from app.routes.story_card import TILE_COLOURS, initials, tile_colour

GROUPS = {"in_use": "In use", "trial": "Free trial", "cancelled": "Cancelled"}
SAMPLE_LABEL = "Sample history"
UPCOMING_DAYS = 30
SPEND_MONTHS = 6


def live_label(settings: Settings) -> str:
    """Honest source label (R7): mock mode's PayPal is simulated, so it doesn't claim the sandbox."""
    return "Live in PayPal Sandbox ✓" if settings.is_sandbox else "Live demo · simulated PayPal"


def today(svc: Services) -> date:
    return (run_day0(svc) + timedelta(days=svc.day)).date()


def _date(svc: Services, sub: Subscription, day: int) -> date:
    at = date_of_day(sub, day)
    return (at or run_day0(svc) + timedelta(days=day)).date()


def _ago(now: date, d: date | None) -> str:
    if d is None:
        return "Not opened yet"
    gap = (now - d).days
    return "Today" if gap <= 0 else "Yesterday" if gap == 1 else cal(d)  # type: ignore[arg-type]


def _risk_tone(risk: int | None) -> str:
    return "high" if (risk or 0) >= 60 else "mid" if (risk or 0) >= 30 else "low"


def _charges_done(svc: Services, sub: Subscription) -> list[int]:
    """Sim days a live subscription was charged (the simulated billing date, `charge_due` in the audit log)."""
    return [e.sim_day for e in svc.store.audit.entries() if e.event == "charge_due" and e.subscription_id == sub.id]


def _group_live(c: dict[str, Any], svc: Services) -> str:
    if c["status"] == "CANCELLED":
        return "cancelled"
    end = c.get("trial_end_day")
    return "trial" if end is not None and svc.day <= end else "in_use"


def live_row(svc: Services, sub: Subscription, c: dict[str, Any], uid: str) -> dict[str, Any]:
    now, group = today(svc), _group_live(c, svc)
    cycles = sub.consent_snapshot.billing_cycles if sub.consent_snapshot else []
    row: dict[str, Any] = {
        "id": sub.id, "source": "live", "source_label": live_label(svc.settings), "merchant": c["merchant"],
        "initials": initials(c["merchant"]), "tile": tile_colour(sub.merchant_id), "plan": c["plan"],
        "group": group, "status_text": GROUPS[group], "risk": c.get("risk"), "risk_tone": _risk_tone(c.get("risk")),
        "last_used": _ago(now, _opt_date(svc, sub, last_open_day(svc.store, sub.owner_id, sub.merchant_id, svc.day))),
        "action": {"label": "See evidence", "href": f"/subscriptions/{sub.id}?user={uid}"}}
    if group == "cancelled":
        saved = charges_avoided([sub], sub.owner_id, sub.consent_snapshot.currency if sub.consent_snapshot else "USD")
        row |= {"when_label": "Cancelled", "when_text": cal(_date(svc, sub, sub.cancelled_day or svc.day)),  # type: ignore[arg-type]
                "ended_how": outcome(svc, sub), "saved_text": svc.money(saved) if saved else ""}
    elif sub.next_billing_day is not None:
        price = first_paid_price(cycles)
        row |= {"when_label": "Next charge",
                "when_text": f"{cal(_date(svc, sub, sub.next_billing_day))} · {svc.money(price)}"}  # type: ignore[arg-type]
    return row


def _opt_date(svc: Services, sub: Subscription, day: int | None) -> date | None:
    return _date(svc, sub, day) if day is not None else None


def sample_row(svc: Services, s: SampleSub, i: int) -> dict[str, Any]:
    now = today(svc)
    group = "cancelled" if s.status == "CANCELLED" else "in_use"
    row: dict[str, Any] = {
        "id": s.id, "source": "sample", "source_label": SAMPLE_LABEL, "merchant": s.merchant,
        "initials": initials(s.merchant), "tile": TILE_COLOURS[(i + 2) % len(TILE_COLOURS)],  # unlike the live two
        "plan": f"{s.category} · {s.plan}",
        "group": group, "status_text": GROUPS[group], "risk": s.risk, "risk_tone": _risk_tone(s.risk),
        "last_used": _ago(now, s.used_on(now)), "terms_note": s.terms_note, "action": {"label": "Details"}}
    if group == "cancelled":
        row |= {"when_label": "Cancelled", "when_text": cal(s.ended) if s.ended else "",  # type: ignore[arg-type]
                "ended_how": s.ended_how,
                "saved_text": f"{svc.money(s.saved)}{' ' + s.saved_per if s.saved_per else ''}" if s.saved else ""}
    else:
        nxt = s.next_charges(now, 1)
        row |= {"when_label": "Next charge",
                "when_text": f"{cal(nxt[0])} · {svc.money(s.price)}/mo" if nxt else ""}  # type: ignore[arg-type]
    return row


def subscription_rows(svc: Services, user: str, subs: list[Subscription], cards: list[dict[str, Any]],
                      ) -> dict[str, Any]:
    """The one list (live first, Penwright first), plus the counts for the sidebar's sub-items."""
    live = [live_row(svc, s, c, user) for s, c in zip(subs, cards, strict=True)]
    live.sort(key=lambda r: (r["merchant"] != "Penwright Studio", r["merchant"]))
    rows = live + [sample_row(svc, s, i) for i, s in enumerate(samples(svc.settings.seed_dir, user))]
    counts = {g: sum(1 for r in rows if r["group"] == g) for g in GROUPS}
    return {"rows": rows, "counts": counts, "total": len(rows)}


# ---- money over time ----------------------------------------------------------------------------------
def _upcoming(svc: Services, user: str, subs: list[Subscription], horizon: int) -> list[dict[str, Any]]:
    """Every charge expected in the next `horizon` days, earliest first."""
    now, out = today(svc), []
    for sub in subs:
        if sub.status != "ACTIVE" or sub.next_billing_day is None or sub.consent_snapshot is None:
            continue
        cycles = sub.consent_snapshot.billing_cycles
        plan = first_year_charges(cycles)
        step = next((cycle_days(c) for c in cycles if c.price > 0), 30)
        done = len(_charges_done(svc, sub))
        trial = any(c.tenure_type == "TRIAL" for c in cycles)
        for i, price in enumerate(plan[done:]):
            d = _date(svc, sub, sub.next_billing_day + i * step)
            if (d - now).days > horizon:
                break
            out.append({"at": d, "merchant": svc.merchant(sub.merchant_id).name, "amount": price, "source": "live",
                        "first_after_trial": trial and done == 0 and i == 0})
    for s in samples(svc.settings.seed_dir, user):
        for d in s.next_charges(now, 3):
            if (d - now).days <= horizon:
                out.append({"at": d, "merchant": s.merchant, "amount": s.price, "source": "sample",
                            "first_after_trial": False})
    return sorted(out, key=lambda x: x["at"])


def coming_up(svc: Services, user: str, subs: list[Subscription], n: int = 3) -> list[dict[str, Any]]:
    return [{**x, "date_text": cal(x["at"]), "amount_text": svc.money(x["amount"]),  # type: ignore[arg-type]
             "source_label": SAMPLE_LABEL if x["source"] == "sample" else live_label(svc.settings)}
            for x in _upcoming(svc, user, subs, 366)[:n]]


def saved_so_far(svc: Services, user: str, subs: list[Subscription]) -> dict[str, Any]:
    live = charges_avoided(subs, user, svc.settings.pricing.demo_currency)
    sample = sum((s.saved or Decimal("0") for s in samples(svc.settings.seed_dir, user)), start=Decimal("0.00"))
    return {"total": svc.money(live + sample), "live": svc.money(live), "sample": svc.money(sample),
            "has_sample": sample > 0, "live_label": live_label(svc.settings)}


def analytics(svc: Services, user: str, subs: list[Subscription]) -> dict[str, Any]:
    """The three dashboard charts. Amounts are strings (Decimal); the browser only plots them."""
    now = today(svc)
    mine = [s for s in subs if s.owner_id == user]
    sample = samples(svc.settings.seed_dir, user)
    # 1. upcoming charges, next 30 days, by date and merchant
    by_date: dict[date, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    names: list[str] = []
    for x in _upcoming(svc, user, mine, UPCOMING_DAYS):
        by_date[x["at"]][x["merchant"]] += x["amount"]
        names += [x["merchant"]] if x["merchant"] not in names else []
    upcoming = [{"date": cal(d), **{k: str(v) for k, v in m.items()}} for d, m in sorted(by_date.items())]  # type: ignore[arg-type]
    # 2. monthly spend, last 6 months (charges that really happened)
    months = [_add_months(date(now.year, now.month, 1), -i) for i in range(SPEND_MONTHS - 1, -1, -1)]
    spend: dict[date, dict[str, Decimal]] = {m: defaultdict(Decimal) for m in months}
    spend_names: list[str] = []

    def add(d: date, merchant: str, amount: Decimal) -> None:
        key = date(d.year, d.month, 1)
        if key in spend:
            spend[key][merchant] += amount
            spend_names.extend([merchant] if merchant not in spend_names else [])

    for s in sample:
        for d in s.charge_dates(now):
            add(d, s.merchant, s.price)
    for sub in mine:
        plan = first_year_charges(sub.consent_snapshot.billing_cycles) if sub.consent_snapshot else []
        for i, day in enumerate(_charges_done(svc, sub)):
            if i < len(plan):
                add(_date(svc, sub, day), svc.merchant(sub.merchant_id).name, plan[i])
    monthly = [{"month": f"{m:%b}", **{k: str(spend[m].get(k, Decimal("0"))) for k in spend_names}} for m in months]
    # 3. saved by SubGuard: trials stopped vs price rises avoided
    live_saved = charges_avoided(mine, user, svc.settings.pricing.demo_currency)
    trials = live_saved + sum((s.saved or Decimal("0") for s in sample if s.saved_kind == "trial"), start=Decimal("0"))
    rises = sum((s.saved or Decimal("0") for s in sample if s.saved_kind == "price_rise"), start=Decimal("0"))
    merchants = [m.name for m in svc.store.load("merchants").items] + [s.merchant for s in sample]
    return {"symbol": svc.money(0)[:1] if not svc.money(0)[:1].isdigit() else "",
            "merchants": merchants,  # fixed order, so each merchant keeps its colour across the charts
            "upcoming": {"rows": upcoming, "series": names,
                         "total": svc.money(sum((Decimal(v) for r in upcoming for k, v in r.items() if k != "date"),
                                                start=Decimal("0")))},
            "monthly": {"rows": monthly, "series": spend_names},
            "saved": {"rows": [{"kind": "Trials stopped", "amount": str(trials)},
                               {"kind": "Price rises avoided", "amount": str(rises)}],
                      "total": svc.money(trials + rises)}}


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


# ---- the Overview ------------------------------------------------------------------------------------
def needs_you(c: dict[str, Any]) -> bool:
    st = c["story"]
    return st["state"] in ("checkin", "handoff") or (st["state"] == "trial" and c["can_decide"]) or any(
        b["kind"] == "email" for b in st["buttons"])


def dashboard_context(svc: Services, user: str, subs: list[Subscription], cards: list[dict[str, Any]],
                      ) -> dict[str, Any]:
    """Overview: "Needs your attention" (Penwright's card always first during the demo, then any other live card
    that needs her; "All clear ✓" when nothing does), "Coming up", "Saved so far". Plus the Subscriptions list."""
    ordered = sorted(cards, key=lambda c: (c["merchant_id"] != "penwright", -c["signup_day"]))
    attention = [c for c in ordered if c["merchant_id"] == "penwright" or needs_you(c)]
    owner = svc.user(user)
    return {"attention": attention, "all_clear": not any(needs_you(c) for c in cards),
            "subs_list": subscription_rows(svc, user, subs, cards), "coming_up": coming_up(svc, user, subs),
            "saved": saved_so_far(svc, user, subs), "live_label": live_label(svc.settings),
            "prefs": owner.settings if owner else None}

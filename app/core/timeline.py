"""Priya's Activity: ONE chronological timeline (D-172), from the audit log, her messages and her emails.

Each entry: who (You / SubGuard / PayPal / the merchant), one plain line (<= 70 characters), an optional grey
detail, and at most one action: "View email" or "Proof ▸". System text (ids, PayPal statuses, rule ids) lives only
in Proof and the raw log. Messages SubGuard sent are entries too, with her answer on the same line. Duplicates fold
into one entry: one fine-print review per subscription (hidden-AI-instructions folded in), one check-in, one
answer per message, and the message that restates an event (timer set, cancelled, charge blocked) joins that event.
Every line comes from a recorded event (R7); dates are on the run's one calendar (D-172).
"""

from __future__ import annotations

from typing import Any

from app.core.audit_log import AuditEntry
from app.core.services import Services
from app.core.sub_dates import day_text
from app.core.timeline_types import (
    ASKS,
    FOLDED,
    QUOTE_FIRST,
    RULES,
    Actor,
    Entry,
    ProofRow,
    by_day,
    channels,
    date_label,
    fit,
)
from app.core.timers import review_for, short
from app.core.verdict import UNIT
from app.integrations.paypal_types import first_charge_day, first_paid_price
from app.models import Alert, Notice, Subscription


def _answers(entries: list[AuditEntry], alerts: dict[str, Alert]) -> dict[tuple[str, str], str]:
    """(subscription, message kind) -> her last Keep / Cancel answer. Repeated taps count once."""
    out: dict[tuple[str, str], str] = {}
    for e in entries:
        act = e.details.get("action")
        alert = alerts.get(e.details.get("alert_id", ""))
        if e.event == "alert_action" and act in ("keep", "cancel") and alert is not None:
            out[(alert.subscription_id or "", alert.kind)] = act
    return out


class _Builder:
    def __init__(self, svc: Services, user: str) -> None:
        self.svc = svc
        store = svc.store
        self.subs = {s.id: s for s in store.load("subscriptions").items if s.owner_id == user}
        self.alerts = {a.id: a for a in store.load("alerts").items if a.user_id == user}
        self.notices: dict[str, Notice] = {n.id: n for n in store.load("notices").items
                                           if n.subscription_id in self.subs}
        self.reviews = {r.id: r for r in store.load("reviews").items}
        self.log = [e for e in store.audit.entries() if e.user_id == user or e.subscription_id in self.subs]
        self.answers = _answers(self.log, self.alerts)
        self.out: dict[str, Entry] = {}

    # ---- helpers ---------------------------------------------------------------------------------
    def add(self, e: AuditEntry, key: str, kind: str, actor: Actor, text: str, sub: Subscription | None,
            **kw: Any) -> Entry | None:
        if key in self.out:
            return None
        label = {"you": "You", "subguard": "SubGuard", "paypal": "PayPal"}.get(actor) or (
            self.name(sub) if sub else "Merchant")
        entry = Entry(key=key, kind=kind, day=e.sim_day, seq=e.seq, actor=actor, actor_label=label,
                      text=fit(text), subscription_id=sub.id if sub else None, **kw)
        self.out[key] = entry
        return entry

    def name(self, sub: Subscription) -> str:
        return short(self.svc.merchant(sub.merchant_id).name)

    def first_charge(self, sub: Subscription) -> tuple[str, str]:
        """(amount, date) of the FIRST paid charge, from the consent snapshot (code, not the LLM). Not
        next_billing_day: that moves on to the next cycle once the first charge has happened."""
        cycles = sub.consent_snapshot.billing_cycles if sub.consent_snapshot else []
        if not cycles:
            return "", ""
        return self.svc.money(first_paid_price(cycles)), day_text(sub, first_charge_day(cycles, sub.signup_day))

    def quote(self, sub: Subscription) -> list[ProofRow]:
        review = review_for(self.svc, sub)
        clauses = [c for c in (review.data.clauses if review else []) if c.source != "code"]
        clauses.sort(key=lambda c: QUOTE_FIRST.index(c.type) if c.type in QUOTE_FIRST else len(QUOTE_FIRST))
        if not clauses:
            return []
        text = clauses[0].quote
        return [ProofRow(label="Fine print", value=text if len(text) <= 240 else text[:239] + "…", quote=True)]

    def paypal(self, sub: Subscription, status: str = "") -> list[ProofRow]:
        rows = [ProofRow(label="PayPal subscription", value=sub.paypal_id)]
        return rows + ([ProofRow(label="Status", value=status)] if status else [])

    def message_channels(self, sub_id: str, kind: str) -> str:
        sent = [a for a in self.alerts.values() if a.subscription_id == sub_id and a.kind == kind]
        return channels(sent[0].delivery) if sent else ""


# ---- one handler per audit event; events without one stay in the raw log only ---------------------
def _review(b: _Builder, e: AuditEntry) -> None:
    review = b.reviews.get(e.details.get("review_id", ""))
    sub = b.subs.get(review.subscription_id or "") if review else None
    if review is None or sub is None:  # a check she backed out of has no subscription: raw log only
        return
    d = review.data
    parts = [f"Act by {day_text(sub, d.deadlines.real_cancel_deadline_day)}"]
    if d.injection_flagged:
        parts.append("hidden AI instructions on the page ignored")
    b.add(e, f"review:{sub.id}", "review", "subguard", f"Checked {b.name(sub)}'s fine print: risk {d.risk_score}/100",
          sub, detail=" · ".join(parts), proof=b.paypal(sub) + b.quote(sub))


def _registered(b: _Builder, e: AuditEntry) -> None:
    sub = b.subs.get(e.subscription_id or "")
    if sub is None:
        return
    amount, _ = b.first_charge(sub)
    cycles = sub.consent_snapshot.billing_cycles if sub.consent_snapshot else []
    paid = next((c for c in cycles if c.price > 0), None)
    first = first_charge_day(cycles, sub.signup_day) if cycles else None
    trial = bool(cycles) and cycles[0].price == 0
    detail = (f"Free until {day_text(sub, first - 1)}, then {amount}/{UNIT[paid.interval_unit]}"
              if trial and paid and first is not None else "")
    b.add(e, f"signup:{sub.id}", "signup", "you", f"Started the {b.name(sub)} {'free trial' if trial else 'plan'} "
          "in PayPal", sub, detail=detail, mark="done",
          proof=b.paypal(sub, e.status_after or "ACTIVE")
          + [ProofRow(label="Price you agreed to", value="Saved from the PayPal plan at sign-up")])


def _timer(b: _Builder, e: AuditEntry) -> None:
    sub = b.subs.get(e.subscription_id or "")
    fire, remind = e.details.get("fire_day"), e.details.get("reminder_day")
    if sub is None or not isinstance(fire, int):
        return
    sent = b.message_channels(sub.id, "timer_set")
    parts = [f"Check-in on {day_text(sub, remind)}" if isinstance(remind, int) else "",
             f"Sent by {sent}" if sent else ""]
    text = (f"Set a check-in for {day_text(sub, remind)}: auto-cancel is off, so you decide"  # D-177
            if e.details.get("auto_cancel") is False and isinstance(remind, int)
            else f"Set a safety timer: cancels on {day_text(sub, fire)} if you don't answer")
    b.add(e, f"timer:{sub.id}", "timer", "subguard", text, sub,
          detail=" · ".join(p for p in parts if p), proof=b.paypal(sub)
          + [ProofRow(label="Safety rule", value=RULES["R2"])] + b.quote(sub))


def _no_timer(b: _Builder, e: AuditEntry) -> None:
    sub = b.subs.get(e.subscription_id or "")
    b.add(e, f"timer:{e.subscription_id}", "timer", "subguard", "No auto-cancel for this one", sub, detail=e.reason)


def _message(b: _Builder, e: AuditEntry) -> None:
    alert = b.alerts.get(e.details.get("alert_id", ""))
    if alert is None or alert.kind in FOLDED:
        return
    sub = b.subs.get(alert.subscription_id or "")
    key = f"msg:{alert.kind}:{alert.subscription_id}" if alert.kind in ASKS else f"msg:{alert.id}"
    answer, mark = "", ""
    chosen = b.answers.get((alert.subscription_id or "", alert.kind))
    if chosen:
        answer = f"You chose: {chosen.title()}"
    elif sub is not None and sub.cancelled_by == "timer":
        answer = "No answer"
    elif alert.acknowledged_at is None and (sub is None or (sub.status == "ACTIVE" and sub.kept_day is None)):
        mark = "ask"
    text = f"Asked you: keep {b.name(sub)} or cancel?" if alert.kind == "reminder" and sub else alert.title
    sent = channels(alert.delivery)
    notice = next((x.get("notice_id") for x in alert.actions if x.get("action") == "review_email"), None)
    proof = [ProofRow(label="Safety rule", value=RULES["R2"])] if alert.kind == "reminder" else []
    b.add(e, key, "checkin" if alert.kind == "reminder" else "message", "subguard", text, sub, answer=answer,
          mark=mark, detail=f"Sent by {sent}" if sent else "", email_id=notice if not proof else None,
          proof=proof)


def _kept(b: _Builder, e: AuditEntry) -> None:
    sub = b.subs.get(e.subscription_id or "")
    if sub is None or b.answers.get((sub.id, "reminder")) == "keep":  # her answer is on the check-in line
        return
    amount, when = b.first_charge(sub)
    b.add(e, f"keep:{sub.id}", "keep", "you", f"Kept the {b.name(sub)} trial", sub, mark="done",
          detail=f"SubGuard won't ask again. First charge {amount} on {when}." if when else "SubGuard won't ask again.")


def _cancel(b: _Builder, e: AuditEntry) -> None:
    sub = b.subs.get(e.subscription_id or "")
    if sub is None or e.actor not in ("user", "timer"):
        return
    if not (e.result or "").startswith("ok"):
        b.add(e, f"cancel-failed:{sub.id}:{e.seq}", "cancel_failed", "paypal", "The cancel didn't go through in PayPal",
              sub, detail="Nothing changed. SubGuard keeps watching.",
              proof=b.paypal(sub) + [ProofRow(label="PayPal said", value=e.result or "")])
        return
    amount, when = b.first_charge(sub)
    cycles = sub.consent_snapshot.billing_cycles if sub.consent_snapshot else []
    why = "You confirmed." if e.actor == "user" else "You didn't answer, so your safety timer acted."
    saved = f" No {amount} charge on {when}." if when and cycles \
        and e.sim_day < first_charge_day(cycles, sub.signup_day) else ""
    b.add(e, f"cancel:{sub.id}", "cancel", "paypal", f"Cancelled your {b.name(sub)} subscription", sub,
          mark="done", detail=why + saved,
          proof=b.paypal(sub, f"{e.status_before or 'ACTIVE'} → {e.status_after or 'CANCELLED'}")
          + [ProofRow(label="Safety rule", value=RULES.get(e.rule_id or "", "Cancelled after your tap."))]
          + b.quote(sub))


def _self_cancel(b: _Builder, e: AuditEntry) -> None:
    sub = b.subs.get(e.subscription_id or "")
    if sub is None:
        return
    if e.event == "status_sync" and not (e.status_after == "CANCELLED" and sub.cancelled_by == "external"):
        return
    who: Actor = "you" if e.event == "paypal_autopay_cancel" else "paypal"
    text = f"Cancelled {b.name(sub)} in PayPal" if who == "you" else f"{b.name(sub)} shows as cancelled in PayPal"
    b.add(e, f"cancel:{sub.id}", "cancel", who, text, sub, mark="done",
          proof=b.paypal(sub, f"{e.status_before or 'ACTIVE'} → {e.status_after or 'CANCELLED'}"))


def _drafted(b: _Builder, e: AuditEntry) -> None:
    notice = b.notices.get(e.details.get("notice_id", ""))
    sub = b.subs.get(e.subscription_id or "")
    if notice is None or sub is None or notice.status == "sent":  # the "sent" entry tells it
        return
    b.add(e, f"email:{notice.id}", "email_draft", "subguard", f"Drafted your cancellation email to {b.name(sub)}",
          sub, detail="It waits for you to review and send it.", mark="ask", email_id=notice.id,
          email_label="Review email")


def _sent(b: _Builder, e: AuditEntry) -> None:
    notice = b.notices.get(e.details.get("notice_id", ""))
    sub = b.subs.get(e.subscription_id or "")
    if notice is None or sub is None:
        return
    auto = e.event == "notice_auto_sent"
    b.add(e, f"email:{notice.id}", "email_sent", "subguard" if auto else "you",
          "Sent your cancellation email for you" if auto else f"Sent your cancellation email to {b.name(sub)}", sub,
          mark="done", email_id=notice.id,
          detail="You asked for this at sign-up." if auto else ("You edited SubGuard's draft." if notice.edited
                                                                  else "SubGuard drafted it for you."))


def _charge(b: _Builder, e: AuditEntry) -> None:
    sub = b.subs.get(e.subscription_id or "")
    if sub is None:
        return
    amount, _ = b.first_charge(sub)
    if e.event == "charge_due":
        b.add(e, f"charge:{sub.id}", "charge_due", "merchant", f"Took the first {amount} payment, as you agreed",
              sub, detail="Your paid plan has started.")
        return
    ok = e.result in (None, "", "no_active_subscription")
    sent = b.message_channels(sub.id, "blocked_charge")
    b.add(e, f"charge:{sub.id}", "charge_blocked", "merchant",
          f"Tried to take the first {amount}: nothing to charge" if ok else "First charge: PayPal check failed",
          sub, mark="done" if ok else "",
          detail=" · ".join(p for p in ("PayPal had no active subscription, so you paid nothing" if ok
                                         else e.reason, f"Sent by {sent}" if sent else "") if p),
          proof=b.paypal(sub, f"{e.status_after or 'CANCELLED'} (read live from PayPal)")
          + [ProofRow(label="Safety rule", value=RULES["R7"])])


def _simple(kind: str, actor: Actor, text: str) -> Any:
    def run(b: _Builder, e: AuditEntry) -> None:
        sub = b.subs.get(e.subscription_id or "")
        name = b.name(sub) if sub else "it"
        b.add(e, f"{kind}:{e.seq}", kind, actor, text.format(name=name, not_="" if e.details.get("essential")
                                                             else "not "), sub)
    return run


HANDLERS = {
    "review_run": _review, "subscription_registered": _registered, "timer_created": _timer,
    "timer_not_created": _no_timer, "alert_sent": _message, "timer_kept": _kept, "keep_subscription": _kept,
    "paypal_cancel": _cancel, "paypal_autopay_cancel": _self_cancel, "status_sync": _self_cancel,
    "cancellation_email_drafted": _drafted, "cancellation_email_sent": _sent, "cancellation_email_app_opened": _sent,
    "cancellation_email_gmail_opened": _sent, "notice_auto_sent": _sent, "charge_blocked": _charge,
    "charge_due": _charge,
    "keep_too_late": _simple("keep_late", "you", "Tapped Keep after {name} was already cancelled"),
    "timer_warning_failed": _simple("warn_failed", "subguard", "Couldn't reach you, so auto-cancel stays off"),
    "essential_tag": _simple("essential", "you", "Marked {name} as {not_}essential"),
}


def timeline(svc: Services, user: str) -> list[Entry]:
    """Every entry, newest first (by sim day, then by log order within the day)."""
    b = _Builder(svc, user)
    for e in b.log:
        handler = HANDLERS.get(e.event)
        if handler is not None:
            handler(b, e)
    return sorted(b.out.values(), key=lambda x: (x.day, x.seq), reverse=True)


__all__ = ["Entry", "by_day", "date_label", "timeline"]

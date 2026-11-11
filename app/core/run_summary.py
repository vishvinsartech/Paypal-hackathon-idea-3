"""Live demo "What SubGuard did" table (D-121): the current run only, one plain row per thing SubGuard did.

Built only from the hash-chained audit log, reusing userA's activity wording (app/core/activity.py), plus the
safety decisions the presenter wants to show: every policy decision (allowed or blocked) and any other blocked
entry. Low-level noise (PayPal HTTP calls, clock ticks, demo buttons, status re-reads) stays in the full log.

The current run is userA's latest registered subscription: entries for it, the fine-print review that came
before it, and anything blocked for her since.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.activity import EVENTS
from app.core.audit_log import AuditEntry
from app.core.services import Services


class RunRow(BaseModel):
    seq: int
    day: int
    who: str
    kind: str  # css hook: you | guard | paypal | timer | warn | policy
    text: str
    rule_id: str | None = None
    decision: str = "n/a"  # allowed | blocked | n/a
    proof: str | None = None  # PayPal debug id or SubGuard's request id for PayPal calls


class RunSummary(BaseModel):
    subscription_id: str | None = None
    paypal_id: str | None = None
    rows: list[RunRow] = []
    full_log_entries: int = 0


REVIEW_EVENTS = ("review_run", "prompt_injection_flagged")


def _row(e: AuditEntry, user_name: str) -> RunRow | None:
    if e.decision == "blocked":
        what = "cancel" if e.event == "policy_decision" else e.event.replace("_", " ")
        return RunRow(seq=e.seq, day=e.sim_day, who="Policy", kind="warn", rule_id=e.rule_id, decision="blocked",
                      text=f"Blocked {what}: {e.reason or 'rule not met'}.")
    if e.event == "policy_decision":
        return RunRow(seq=e.seq, day=e.sim_day, who="Policy", kind="policy", rule_id=e.rule_id, decision="allowed",
                      text=f"Allowed the cancel: {e.reason or 'rule met'}.")
    if e.event == "paypal_cancel" and e.actor not in ("user", "timer"):
        return None
    describe = EVENTS.get(e.event)
    res = describe(e) if describe else None
    if res is None:
        return None
    who, kind, text = res
    proof = e.paypal_debug_id or e.paypal_request_id if e.event == "paypal_cancel" else None
    return RunRow(seq=e.seq, day=e.sim_day, who=user_name if who == "You" else who, kind=kind, text=text,
                  rule_id=e.rule_id, decision=e.decision, proof=proof)


def run_summary(svc: Services, user_id: str, user_name: str = "userA") -> RunSummary:
    entries = svc.store.audit.entries()
    starts = [e for e in entries if e.event == "subscription_registered" and e.user_id == user_id]
    out = RunSummary(full_log_entries=len(entries))
    if not starts:
        return out
    start = starts[-1]
    sub_id = start.subscription_id
    out.subscription_id, out.paypal_id = sub_id, start.details.get("paypal_id")
    reviews = [e for e in entries if e.event == "review_run" and e.seq < start.seq]
    review_id = reviews[-1].details.get("review_id") if reviews else None
    picked: list[AuditEntry] = []
    for e in entries:
        if e.event in REVIEW_EVENTS:
            keep = review_id is not None and e.details.get("review_id") == review_id
        elif e.subscription_id == sub_id:
            keep = True
        else:  # e.g. a rate-limit (R4) or token (R3) block with no single subscription
            keep = e.seq > start.seq and e.user_id == user_id and e.decision == "blocked"
        if keep:
            picked.append(e)
    out.rows = [r for r in (_row(e, user_name) for e in picked) if r is not None]
    return out

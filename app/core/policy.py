"""Safety rules R1-R7 (spec 3), enforced in code. The LLM only proposes; this decides.

Every decision (allowed AND blocked) is written to the audit log with its rule id (actor `policy`).
- R1 consent: a cancel needs a valid confirmation token (user tap) or a fired safety timer meeting R2.
- R2 safety timer: shown at creation, warning delivered >= 24 sim-hours (1 sim day) earlier, not kept,
  trial before first charge OR un-agreed price rise with auto_cancel_price_rises, before the billing date.
- R3 token: single-use, 5 minutes, bound to user + exact sorted subscription ids.
- R4 limits: <= 10 subscriptions per command, <= 5 PayPal writes per minute per user.
- R5 ownership. R6 essential: never auto-cancelled (manual + confirmation is fine).
- R7 no fake claims: callers report only gateway-confirmed results (see actions.py).
"""

from __future__ import annotations

import secrets
import time
from collections import deque
from collections.abc import Callable
from datetime import timedelta

from pydantic import BaseModel

from app.models import ConfirmToken, Subscription, Timer, User
from app.store import JsonStore, utcnow

TOKEN_TTL = timedelta(minutes=5)
MAX_PER_COMMAND = 10
MAX_WRITES_PER_MINUTE = 5


class Decision(BaseModel):
    allowed: bool
    rule_id: str
    reason: str
    subscription_id: str | None = None


class Policy:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._writes: dict[str, deque[float]] = {}

    # ---- audit ----------------------------------------------------------------------
    @staticmethod
    def record(store: JsonStore, d: Decision, *, user_id: str | None, action: str, requested_by: str) -> Decision:
        store.audit.append(actor="policy", event="policy_decision", user_id=user_id, subscription_id=d.subscription_id,
                           rule_id=d.rule_id, decision="allowed" if d.allowed else "blocked", reason=d.reason,
                           details={"action": action, "requested_by": requested_by})
        return d

    # ---- R3 tokens -------------------------------------------------------------------
    def issue_token(self, store: JsonStore, user_id: str, sub_ids: list[str]) -> ConfirmToken | Decision:
        """Called when the user is shown a confirmation card. R4 (count) and R5 are checked up front too."""
        pre = self._precheck(store, user_id, sub_ids)
        if pre is not None:
            return self.record(store, pre, user_id=user_id, action="issue_token", requested_by="user")
        now = utcnow()
        tok = ConfirmToken(token=secrets.token_urlsafe(24), user_id=user_id, subscription_ids=sorted(sub_ids),
                           issued_at=now, expires_at=now + TOKEN_TTL)
        with store.edit("tokens") as tokens:
            tokens.items = [t for t in tokens.items if t.expires_at > now - timedelta(hours=1)] + [tok]
        store.audit.append(actor="system", event="confirm_token_issued", user_id=user_id, rule_id="R3",
                           details={"subscriptions": tok.subscription_ids, "expires_at": tok.expires_at.isoformat(),
                                    "token": tok.token})
        return tok

    def _precheck(self, store: JsonStore, user_id: str, sub_ids: list[str]) -> Decision | None:
        if not sub_ids:
            return Decision(allowed=False, rule_id="R1", reason="No subscriptions were selected")
        if len(sub_ids) > MAX_PER_COMMAND:
            return Decision(allowed=False, rule_id="R4",
                            reason=f"At most {MAX_PER_COMMAND} subscriptions per command ({len(sub_ids)} asked)")
        subs = {s.id: s for s in store.load("subscriptions").items}
        for sid in sub_ids:
            if sid not in subs or subs[sid].owner_id != user_id:
                return Decision(allowed=False, rule_id="R5", subscription_id=sid,
                                reason="You can only act on your own subscriptions")
        return None

    def _consume(self, store: JsonStore, user_id: str, sub_ids: list[str], token: str) -> Decision | None:
        now = utcnow()
        with store.edit("tokens") as tokens:
            tok = next((t for t in tokens.items if t.token == token), None)
            problem = None
            if tok is None:
                problem = "Confirmation token not recognised"
            elif tok.used_at is not None:
                problem = "Confirmation token was already used"
            elif tok.expires_at <= now:
                problem = "Confirmation token expired (valid 5 minutes)"
            elif tok.user_id != user_id:
                problem = "Confirmation token belongs to another user"
            elif tok.subscription_ids != sorted(sub_ids):
                problem = "Confirmation token was issued for a different set of subscriptions"
            if tok is not None and problem is None:
                tok.used_at = now
        event = "confirm_token_used" if problem is None else "confirm_token_rejected"
        store.audit.append(actor="system", event=event, user_id=user_id, rule_id="R3", reason=problem,
                           decision="allowed" if problem is None else "blocked",
                           details={"subscriptions": sorted(sub_ids)})
        return None if problem is None else Decision(allowed=False, rule_id="R3", reason=problem)

    # ---- R1 manual cancel ------------------------------------------------------------
    def check_user_cancel(self, store: JsonStore, user_id: str, sub_ids: list[str], token: str | None,
                          requested_by: str = "user") -> list[Decision]:
        """All-or-nothing gate for one confirmed command. Consumes the token on success."""
        blocked = self._precheck(store, user_id, sub_ids)
        if blocked is None and not token:
            blocked = Decision(allowed=False, rule_id="R1",
                               reason="A cancel needs your confirmation tap; nothing was cancelled")
        if blocked is None:
            blocked = self._consume(store, user_id, sub_ids, token or "")
        if blocked is not None:
            return [self.record(store, blocked, user_id=user_id, action="cancel", requested_by=requested_by)]
        return [self.record(store, Decision(allowed=True, rule_id="R1", subscription_id=sid,
                                            reason="Confirmed by the user's tap (single-use token)"),
                            user_id=user_id, action="cancel", requested_by=requested_by) for sid in sorted(sub_ids)]

    # ---- R2 timer --------------------------------------------------------------------
    def check_timer_fire(self, store: JsonStore, timer: Timer, sub: Subscription, user: User | None,
                         day: int) -> Decision:
        d = self._timer_decision(timer, sub, user, day)
        return self.record(store, d, user_id=sub.owner_id, action=f"auto_cancel:{timer.kind}", requested_by="timer")

    @staticmethod
    def _timer_decision(timer: Timer, sub: Subscription, user: User | None, day: int) -> Decision:
        def block(rule: str, reason: str) -> Decision:
            return Decision(allowed=False, rule_id=rule, reason=reason, subscription_id=sub.id)

        if user is None or sub.owner_id != user.id or timer.subscription_id != sub.id:
            return block("R5", "Timer and subscription owner don't match")
        if sub.essential:
            return block("R6", "Tagged essential: SubGuard never auto-cancels it")
        if timer.status != "PENDING":
            return block("R2", f"Timer is {timer.status}, not pending")
        if not timer.shown_to_user:
            return block("R2", "The timer was never shown to the user")
        if not timer.warning_delivered or timer.warned_day is None or timer.warned_day > day - 1:
            return block("R2", "No warning was delivered at least 24 sim-hours before firing")
        billing = timer.billing_day if timer.billing_day is not None else sub.next_billing_day
        if billing is None or day >= billing or sub.next_billing_day != billing:
            return block("R2", "Too late: the billing date has been reached")
        if timer.kind == "price_rise" and not user.settings.auto_cancel_price_rises:
            return block("R2", "auto_cancel_price_rises is off for this user")
        why = "trial before the first charge" if timer.kind == "trial" else "price rise the user didn't agree to"
        return Decision(allowed=True, rule_id="R2", subscription_id=sub.id,
                        reason=f"Warned on day {timer.warned_day}, not kept, {why}, before billing day {billing}")

    # ---- R4 rate ---------------------------------------------------------------------
    def take_write(self, store: JsonStore, user_id: str, sub_id: str, requested_by: str) -> Decision | None:
        """Reserve one PayPal write for this user; None if allowed, else the (audited) R4 block."""
        now = self.clock()
        window = self._writes.setdefault(user_id, deque())
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= MAX_WRITES_PER_MINUTE:
            d = Decision(allowed=False, rule_id="R4", subscription_id=sub_id,
                         reason=f"Rate limit: at most {MAX_WRITES_PER_MINUTE} PayPal writes per minute")
            return self.record(store, d, user_id=user_id, action="paypal_write", requested_by=requested_by)
        window.append(now)
        return None

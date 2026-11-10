"""Deadline maths and the 0-100 risk score (spec 7.2 steps 3 and 5). Deterministic code, never the LLM.

risk = min(100, Σ type weights (each type counted once)
                + style penalties (font < 11px: +8, contrast < 3:1: +8, pre-ticked box: +10, hidden text: +6)
                + money factor min(15, year-one cost / 50)
                + dark-pattern library bonus (0-10))
PROMPT_INJECTION_ATTEMPT weighs 0: an injection is flagged but never moves the score (D-043).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.integrations.capture import PageCapture
from app.review_types import Clause, Deadlines, RiskBreakdown

TYPE_WEIGHTS: dict[str, int] = {
    "AUTO_RENEW": 10, "INTRO_PRICE_STEP_UP": 6, "PRECHECKED_ADDON": 3, "NOTICE_PERIOD": 12,
    "EARLY_TRIAL_TERMINATION": 3, "HARD_CANCEL": 8, "HIDDEN_TEXT_STYLE": 1, "TERMS_MISMATCH": 4,
    "PROMPT_INJECTION_ATTEMPT": 0, "CLEAR_TERMS": 0,
}
STYLE_PENALTIES = {"small_font": 8, "low_contrast": 8, "prechecked_box": 10, "hidden_text": 6}
MIN_TERMS_LEN = 20  # ignore short UI labels when looking for tiny / grey / hidden terms


def style_signals(capture: PageCapture) -> list[str]:
    """Which style penalties apply. Small/grey text is judged on the checkout page; hidden text anywhere."""
    main = [b for b in capture.main_blocks() if len(b.text) >= MIN_TERMS_LEN and not b.hidden]
    signals = []
    if any(b.font_px < 11 for b in main):
        signals.append("small_font")
    if any(b.contrast < 3 for b in main):
        signals.append("low_contrast")
    if any(c.checked for c in capture.checkboxes):
        signals.append("prechecked_box")
    if any(b.hidden and len(b.text) >= MIN_TERMS_LEN for b in capture.blocks):
        signals.append("hidden_text")
    return signals


def score(clauses: list[Clause], signals: list[str], year_one: Decimal, bonus: int) -> RiskBreakdown:
    types = {c.type for c in clauses}
    type_points = {t: TYPE_WEIGHTS[t] for t in sorted(types) if TYPE_WEIGHTS[t]}
    style_points = {s: STYLE_PENALTIES[s] for s in signals}
    money = min(Decimal("15"), year_one / Decimal("50")).quantize(Decimal("0.01"))
    raw = Decimal(sum(type_points.values()) + sum(style_points.values()) + bonus) + money
    total = min(100, int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    return RiskBreakdown(type_points=type_points, style_points=style_points, money_factor=money,
                         library_bonus=bonus, total=total)


def compute_deadlines(signup_day: int, first_charge_day: int, notice_days: int, *, layer2: bool) -> Deadlines:
    """deadline = first charge - notice - 1 (safety buffer); timer = deadline - 1 (Layer 2: - 2);
    reminder = timer - 1. Under 24 sim-hours between signup and the timer -> no auto-cancel timer."""
    deadline = first_charge_day - notice_days - 1
    timer = deadline - (2 if layer2 else 1)
    reminder = timer - 1
    allowed = timer >= signup_day + 1
    note = "" if allowed else ("Too little time to warn you 24 hours ahead, so SubGuard won't auto-cancel. "
                               "Please decide at signup.")
    return Deadlines(signup_day=signup_day, first_charge_day=first_charge_day, notice_days=notice_days,
                     real_cancel_deadline_day=deadline, timer_fire_day=timer, reminder_day=max(reminder, signup_day),
                     layer2=layer2, auto_timer_allowed=allowed, note=note)

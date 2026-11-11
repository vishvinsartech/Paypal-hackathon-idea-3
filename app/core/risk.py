"""Deadline maths and the 0-100 risk score (spec 7.2 steps 3 and 5). Deterministic code, never the LLM.

risk = min(100, Σ type weights (each type counted once)
                + hard-to-read terms +10, counted once (font < 11px, contrast < 3:1, hidden text or a
                  HIDDEN_TEXT_STYLE finding: the same small grey text used to score three times, A4)
                + pre-ticked box +10
                + money factor min(15, year-one cost / 50)
                + dark-pattern library bonus (1 per matched type, 0-5))
AUTO_RENEW weighs 4: every subscription renews. PROMPT_INJECTION_ATTEMPT weighs 0: an injection is flagged but
never moves the score (D-043), and hidden injection text doesn't count as hard-to-read either.
Calibration (asserted in tests): Penwright 87, Quillnote 73, an honest monthly plan <= 25 (D-143).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.core.patterns import INJECTION_RE
from app.integrations.capture import PageCapture
from app.review_types import Clause, Deadlines, RiskBreakdown

TYPE_WEIGHTS: dict[str, int] = {
    "AUTO_RENEW": 4, "INTRO_PRICE_STEP_UP": 10, "PRECHECKED_ADDON": 3, "NOTICE_PERIOD": 20,
    "EARLY_TRIAL_TERMINATION": 4, "HARD_CANCEL": 14, "HIDDEN_TEXT_STYLE": 0, "TERMS_MISMATCH": 9,
    "PROMPT_INJECTION_ATTEMPT": 0, "CLEAR_TERMS": 0,
}
HARD_TO_READ = 10  # once, whatever the reason (A4)
HARD_TO_READ_SIGNALS = frozenset({"small_font", "low_contrast", "hidden_text"})
STYLE_PENALTIES = {"hard_to_read": HARD_TO_READ, "prechecked_box": 10}
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
    if any(b.hidden and len(b.text) >= MIN_TERMS_LEN and not INJECTION_RE.search(b.text) for b in capture.blocks):
        signals.append("hidden_text")
    return signals


def score(clauses: list[Clause], signals: list[str], year_one: Decimal, bonus: int) -> RiskBreakdown:
    types = {c.type for c in clauses}
    type_points = {t: TYPE_WEIGHTS[t] for t in sorted(types) if TYPE_WEIGHTS[t]}
    style_points: dict[str, int] = {}
    if HARD_TO_READ_SIGNALS & set(signals) or "HIDDEN_TEXT_STYLE" in types:
        style_points["hard_to_read"] = HARD_TO_READ
    if "prechecked_box" in signals:
        style_points["prechecked_box"] = STYLE_PENALTIES["prechecked_box"]
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
                     real_cancel_deadline_day=deadline, terms_last_day=first_charge_day - notice_days,
                     timer_fire_day=timer, reminder_day=max(reminder, signup_day),
                     layer2=layer2, auto_timer_allowed=allowed, note=note)

"""Fine-print review pipeline (spec 7.2): capture -> LLM findings (verbatim-checked) -> code checks -> risk.

The LLM only proposes findings. Code verifies every quote, adds what it can detect itself (prompt injection,
hidden-text style, PayPal mismatch), does all money and deadline maths from the PayPal plan, and scores.
LLM down / invalid twice -> rule-based extractor, labelled "basic check (AI unavailable)".
"""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.core.crosscheck import cross_check
from app.core.durations import duration_days, mentions_duration
from app.core.patterns import (
    drop_clear_terms_if_risky,
    fallback_extract,
    find_injections,
    label_similar,
    library_bonus,
    library_matches,
    load_library,
    quote_ok,
)
from app.core.risk import compute_deadlines, score, style_signals
from app.core.savings import year_one_cost
from app.integrations.capture import PageCapture
from app.integrations.paypal_types import PlanView, first_charge_day
from app.llm.base import LLMError, LLMProvider
from app.models import Merchant, Review
from app.review_types import (
    BasicCheck,
    Clause,
    Deadlines,
    PayPalCheckRow,
    ReviewData,
    ReviewResult,
    RiskBreakdown,
)
from app.store import JsonStore, utcnow

BASIC_LABEL = "basic check (AI unavailable)"
NOTICE_DAYS_RE = re.compile(r"(\d+)\s+(?:calendar\s+|business\s+)?days?\b", re.I)
PLAN_MONEY_TYPES = ("AUTO_RENEW", "INTRO_PRICE_STEP_UP")


@dataclass
class _Assembled:
    clauses: list[Clause]
    rows: list[PayPalCheckRow]
    deadlines: Deadlines
    risk: RiskBreakdown
    signals: list[str]
    matches: list[str]
    year_one: Decimal
    notice_source: str


class Auditor:
    def __init__(self, provider: LLMProvider, store: JsonStore, library_path: Path, timeout: float) -> None:
        self.provider = provider
        self.store = store
        self.library_path = library_path
        self.timeout = timeout

    # ---- LLM with verification, one retry, fallback ---------------------------------
    def _audit_llm(self, user_id: str | None, ok: bool, started: float, usage: dict[str, object],
                   err: str = "") -> None:
        self.store.audit.append(
            actor="system", event="llm_call", user_id=user_id, result="ok" if ok else f"error:{err}",
            details={"purpose": "review", "provider": self.provider.name, "model": self.provider.model,
                     "latency_ms": int((time.perf_counter() - started) * 1000), **usage})

    async def _ask(self, capture: PageCapture, user_id: str | None) -> tuple[ReviewResult | None, list[str]]:
        feedback: str | None = None
        dropped: list[str] = []
        partial: ReviewResult | None = None
        for attempt in (1, 2):
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(self.provider.extract_findings(capture, feedback=feedback),
                                                self.timeout)
            except (LLMError, TimeoutError) as exc:
                self._audit_llm(user_id, False, started, {}, type(exc).__name__ + ":" + str(exc)[:120])
                continue
            self._audit_llm(user_id, True, started, dict(result.usage))
            bad = [c for c in result.clauses if not quote_ok(c.quote, capture)]
            result.clauses = [c for c in result.clauses if c not in bad]
            if bad and attempt == 1:  # hallucinated quote(s): drop them and ask once more
                dropped += [c.quote for c in bad]
                partial = result
                feedback = (f"{len(bad)} quote(s) were not found verbatim in the page text: "
                            + " | ".join(c.quote[:80] for c in bad))
                continue
            dropped += [c.quote for c in bad]
            return result, dropped
        return partial, dropped

    # ---- code checks --------------------------------------------------------------
    @staticmethod
    def _style_clause(capture: PageCapture) -> Clause | None:
        main = [b for b in capture.main_blocks() if len(b.text) >= 20 and not b.hidden]
        tiny = sorted((b for b in main if b.font_px < 11 or b.contrast < 3), key=lambda b: b.font_px)
        hidden = [b for b in capture.blocks if b.hidden and len(b.text) >= 20]
        block = (tiny or hidden or [None])[0]
        if block is None:
            return None
        how = (f"{block.font_px:.0f}px text at {block.contrast:.1f}:1 contrast" if block in tiny
               else f"text hidden on the page ({block.hidden_reason})")
        return Clause(type="HIDDEN_TEXT_STYLE", quote=block.text, severity=3, evidence_testid=block.testid,
                      source="code", plain_english=f"Important terms are hard to see: {how}.")

    @staticmethod
    def _notice_days(clauses: list[Clause], llm_value: int | None) -> tuple[int, str]:
        """A3: the notice period from a verified NOTICE_PERIOD quote. Code parses digits or words ("3 days",
        "seventy-two hours" -> 3). When the quote states a duration code can't read, the AI's value is accepted.
        No verified notice quote -> 0 (nothing to act on). Returns (days, source)."""
        for c in clauses:
            if c.type != "NOTICE_PERIOD":
                continue
            if (days := duration_days(c.quote)) is not None:
                return days, "quote_digits" if NOTICE_DAYS_RE.search(c.quote) else "quote_words"
            if llm_value is not None and mentions_duration(c.quote):
                return max(0, llm_value), "ai"
        return 0, "none"

    def _assemble(self, capture: PageCapture, plan: PlanView, result: ReviewResult, *, merchant: Merchant,
                  signup_day: int) -> _Assembled:
        """Code checks, deadlines and the score on top of one set of findings (AI or basic): the same steps for
        both, so the A2 comparison shows only what the AI adds."""
        clauses = list(result.clauses)
        if not any(c.type == "PROMPT_INJECTION_ATTEMPT" for c in clauses):
            clauses += find_injections(capture)
        signals = style_signals(capture)
        if signals and not any(c.type == "HIDDEN_TEXT_STYLE" for c in clauses):
            if (style := self._style_clause(capture)) is not None:
                clauses.append(style)
        rows, mismatch = cross_check(capture, plan, result)
        if mismatch is not None:
            clauses.append(mismatch)
        clauses = drop_clear_terms_if_risky(clauses)

        y1 = year_one_cost(plan.billing_cycles)
        notice, source = self._notice_days(clauses, result.notice_days)
        deadlines = compute_deadlines(signup_day, first_charge_day(plan.billing_cycles, signup_day), notice,
                                      layer2=not merchant.fair_trial_member)
        for c in clauses:  # PayPal values win for all money maths; LLM money hints are discarded
            c.money_impact_usd_year = y1 if c.type in PLAN_MONEY_TYPES else None
            if c.type == "NOTICE_PERIOD":
                c.deadline_day = deadlines.real_cancel_deadline_day

        library = load_library(str(self.library_path))
        matches = library_matches(capture, library)
        label_similar(clauses, library)
        risk = score(clauses, signals, y1, library_bonus(matches))
        clauses.sort(key=lambda c: -c.severity)
        return _Assembled(clauses, rows, deadlines, risk, signals, [e.id for e in matches], y1, source)

    async def review(self, capture: PageCapture, plan: PlanView, *, merchant: Merchant, plan_key: str | None,
                     signup_day: int, user_id: str | None = None) -> ReviewData:
        result, dropped = await self._ask(capture, user_id)
        mode = "ai" if result is not None else "basic"
        basic_result = ReviewResult(clauses=fallback_extract(capture))  # A2: cheap, run with every review
        if result is None:
            result = basic_result
        out = self._assemble(capture, plan, result, merchant=merchant, signup_day=signup_day)
        base = out if mode == "basic" else self._assemble(capture, plan, basic_result.model_copy(deep=True),
                                                          merchant=merchant, signup_day=signup_day)
        basic = BasicCheck(types=[c.type for c in base.clauses], clauses=base.clauses,
                           notice_days=base.deadlines.notice_days,
                           real_cancel_deadline_day=base.deadlines.real_cancel_deadline_day,
                           terms_last_day=base.deadlines.terms_last_day or 0, risk_score=base.risk.total)
        return ReviewData(
            merchant_id=merchant.id, page_url=capture.url, plan_id=plan.id, plan_key=plan_key, mode=mode,
            mode_label="AI review" if mode == "ai" else BASIC_LABEL, provider=self.provider.name,
            model=self.provider.model, summary=result.summary, clauses=out.clauses, paypal_check=out.rows,
            deadlines=out.deadlines, risk=out.risk, risk_score=out.risk.total, currency=plan.currency,
            year_one_cost=out.year_one, style_signals=out.signals, library_matches=out.matches,
            dropped_quotes=dropped, injection_flagged=any(c.type == "PROMPT_INJECTION_ATTEMPT" for c in out.clauses),
            notice_source=out.notice_source, basic=basic,  # type: ignore[arg-type]
        )


def save_review(store: JsonStore, data: ReviewData, sim_day: int, subscription_id: str | None = None) -> Review:
    review = Review(id=f"rev-{secrets.token_hex(5)}", merchant_id=data.merchant_id, subscription_id=subscription_id,
                    created_at=utcnow(), sim_day=sim_day, risk_score=data.risk_score, data=data)
    with store.edit("reviews") as reviews:
        reviews.items.append(review)
    return review

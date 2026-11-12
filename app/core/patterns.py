"""Deterministic text rules: the dark-pattern library (regex + TF-IDF), the prompt-injection detector, and
the rule-based fallback extractor used when the LLM is unavailable ("basic check (AI unavailable)")."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.integrations.capture import PageCapture, normalize_ws
from app.review_types import Clause

INJECTION_RE = re.compile(
    r"\b(note|message|instructions?)s? (to|for) (ai|llms?|language models?|assistants?|reviewers?)\b"
    r"|\bignore (all |any )?(previous|prior|above) instructions\b"
    r"|\breport (the )?risk as\b|\b(ai|assistant)s? (must|should) (say|report|rate)\b",
    re.I,
)

# (type, regex, severity, plain English) for the fallback extractor. Quotes are whole sentences from the page.
FALLBACK_RULES: list[tuple[str, str, int, str]] = [
    ("AUTO_RENEW", r"automatically (converts|renews)|auto-?renews?", 3,
     "This renews or converts to a paid plan automatically unless you cancel."),
    ("INTRO_PRICE_STEP_UP", r"after \d+ (paid )?months?,? the price", 4, "The price goes up after a few months."),
    ("PRECHECKED_ADDON", r"selected by default|unless you untick", 4, "An extra paid add-on is ticked for you."),
    ("NOTICE_PERIOD", r"notice\b.{0,60}\bat least \d+ days? before", 5,
     "You must give notice days before billing, so the real deadline is earlier."),
    ("EARLY_TRIAL_TERMINATION", r"trial ends (immediately|early)", 4,
     "The trial can end early, so paying starts sooner."),
    ("HARD_CANCEL", r"no online cancel|weekdays?\b.{0,40}\bonly", 4, "Cancelling is made hard (no cancel button)."),
    ("CLEAR_TERMS", r"cancel anytime", 1, "Cancelling is easy and clearly explained."),
]


class LibraryEntry(BaseModel):
    id: str
    type: str
    dark: bool
    regex: str = ""
    example: str


def sentences(text: str) -> list[str]:
    return [s for s in (normalize_ws(x) for x in re.split(r"(?<=[.!?])\s+", text)) if s]


def quote_ok(quote: str, capture: PageCapture) -> bool:
    q = normalize_ws(quote)
    return bool(q) and q in normalize_ws(capture.full_text)


@lru_cache(maxsize=4)
def load_library(path: str) -> tuple[LibraryEntry, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(LibraryEntry.model_validate(e) for e in data["items"])


def library_matches(capture: PageCapture, library: tuple[LibraryEntry, ...]) -> list[LibraryEntry]:
    text = normalize_ws(capture.full_text)
    return [e for e in library if e.dark and e.regex and re.search(e.regex, text, re.I)]


def library_bonus(matches: list[LibraryEntry]) -> int:
    """0-5: one point per distinct dark-pattern type the page text matches (A4)."""
    return min(5, len({e.type for e in matches}))


def label_similar(clauses: list[Clause], library: tuple[LibraryEntry, ...], threshold: float = 0.2) -> None:
    """Attach the nearest library example (TF-IDF cosine) to each clause. Informational only."""
    if not clauses or not library:
        return
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    vec = TfidfVectorizer(stop_words="english").fit([e.example for e in library] + [c.quote for c in clauses])
    sims = cosine_similarity(vec.transform([c.quote for c in clauses]), vec.transform([e.example for e in library]))
    for clause, row in zip(clauses, sims, strict=True):
        same_type = [i for i, e in enumerate(library) if e.type == clause.type]
        if not same_type:
            continue
        best = max(same_type, key=lambda i: row[i])
        if row[best] >= threshold:
            clause.similar_pattern = library[best].id


def find_injections(capture: PageCapture) -> list[Clause]:
    found: list[Clause] = []
    for block in capture.blocks:
        for sent in sentences(block.text):
            if INJECTION_RE.search(sent):
                where = f"hidden ({block.hidden_reason}) " if block.hidden else ""
                found.append(Clause(
                    type="PROMPT_INJECTION_ATTEMPT", quote=block.text if len(block.text) < 300 else sent,
                    plain_english=f"The page has {where}text giving instructions to AI helpers. SubGuard ignored it.",
                    severity=5, evidence_testid=block.testid, source="code"))
                break
    return found


NOT_RISKY = frozenset({"CLEAR_TERMS", "AUTO_RENEW", "PROMPT_INJECTION_ATTEMPT"})


def drop_clear_terms_if_risky(clauses: list[Clause]) -> list[Clause]:
    """B10: "clear terms" can't sit next to dark patterns. Drop CLEAR_TERMS when any risky type is present
    (AI and basic paths alike). CLEAR_TERMS weighs 0, so the score doesn't change."""
    if any(c.type not in NOT_RISKY for c in clauses):
        return [c for c in clauses if c.type != "CLEAR_TERMS"]
    return clauses


def fallback_extract(capture: PageCapture) -> list[Clause]:
    """Regex extractor: never invents anything; every quote is a sentence from the page."""
    out: list[Clause] = []
    seen: set[str] = set()
    for block in capture.blocks:
        for sent in sentences(block.text):
            for ctype, rx, severity, plain in FALLBACK_RULES:
                if ctype in seen or not re.search(rx, sent, re.I):
                    continue
                seen.add(ctype)
                out.append(Clause(type=ctype, quote=sent, plain_english=plain,  # type: ignore[arg-type]
                                  severity=severity, evidence_testid=block.testid, source="rules"))
    return out

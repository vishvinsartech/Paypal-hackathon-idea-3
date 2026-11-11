"""Durations written in words or digits (A3): "seventy-two hours" -> 3 days, "3 days" -> 3, "two weeks" -> 14.

Code parses the notice period from the verified quote; the LLM's own `notice_days` is only a fallback when the
quote clearly states a duration that this parser can't read. Also renders numbers as words for the shop pages
(Quillnote's terms state the notice period in words, so the basic regex check can't find it).
"""

from __future__ import annotations

import math
import re

UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
WORD_VALUE = {w: i for i, w in enumerate(UNITS)} | {w: i * 10 for i, w in enumerate(TENS) if w}

_UNIT_RX = "|".join(UNITS[1:10])
_NUM_WORD = rf"(?:(?:{'|'.join(TENS[2:])})(?:[-\s](?:{_UNIT_RX}))?|{'|'.join(reversed(UNITS))})"
DURATION_RE = re.compile(
    rf"\b(\d+|{_NUM_WORD})[\s-]+(?:\(\d+\)\s+)?(?:full\s+|calendar\s+|business\s+|working\s+)?(hours?|days?|weeks?)\b",
    re.I)
MENTIONS_DURATION_RE = re.compile(r"\b(hours?|days?|weeks?)\b", re.I)


def number_words(n: int) -> str:
    """0-99 in words ("seventy-two"); larger numbers stay digits."""
    if 0 <= n < 20:
        return UNITS[n]
    if 20 <= n < 100:
        tens, unit = divmod(n, 10)
        return TENS[tens] + (f"-{UNITS[unit]}" if unit else "")
    return str(n)


def _word_number(text: str) -> int:
    if text.isdigit():
        return int(text)
    return sum(WORD_VALUE[part] for part in re.split(r"[-\s]+", text.lower()) if part)


def duration_days(text: str) -> int | None:
    """The first duration in the text, in whole days (hours round up: 72 h -> 3 days, 50 h -> 3 days)."""
    m = DURATION_RE.search(text)
    if m is None:
        return None
    value, unit = _word_number(m.group(1)), m.group(2).lower()
    if unit.startswith("hour"):
        return math.ceil(value / 24)
    if unit.startswith("week"):
        return value * 7
    return value


def mentions_duration(text: str) -> bool:
    return bool(MENTIONS_DURATION_RE.search(text))

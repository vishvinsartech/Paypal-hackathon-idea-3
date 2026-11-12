"""Shared demo-video logic (no ffmpeg, no browser): scenes.json v2, the timeline, narration words, VIDEO_SCRIPT.md.

Used by check_scenes.py, make_voiceover.py, record_demo.py, record_stage.py, build_video.py and the tests.
Scene kinds (D-184): "card" (title / end card), "slide" (motion-graphic slide on the stage), "app" (the app,
recorded with Playwright, shown in the stage's browser frame) and "paypal" (real PayPal sandbox pages in the same
frame; sandbox takes only; in mock mode its time goes to its "mock_fallback" scene).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DV = ROOT / "demo-video"
SCENES_PATH = DV / "scenes.json"
STAGE_HTML = DV / "stage" / "stage.html"
OUT = DV / "out"
HARD_LIMIT_SECONDS = 180  # the hackathon's "under 3 minutes"; scenes.json keeps a margin below it
KINDS = ("card", "slide", "app", "paypal")
RECORDED = ("app", "paypal")  # kinds that show a recording in the stage's browser frame
ON_RE = re.compile(r"\{on:(\d+)\}")
FACT_RE = re.compile(r"\{fact:([a-z_]+)\}")
SUB_RE = re.compile(r"\{sub:([a-z0-9-]+)\}")
ACCENT_RE = re.compile(r"(\*?)(.*?)(\*?)([.,;:!?)]*)")  # *word*, *start ... end*, punctuation after the star
# CLAUDE.md "No real brands": narration never names one (PayPal is the platform we build on). URLs are stripped
# first. The end card's chips (stage.html) are not narration.
BRANDS = ("Gmail", "Google", "Outlook", "Yahoo", "Apple", "iCloud", "Microsoft", "Amazon", "Netflix", "Spotify",
          "Adobe", "Notion", "Grammarly", "Evernote", "Slack", "Zapier", "GitHub", "Anthropic", "Claude", "OpenAI",
          "ChatGPT", "GPT", "Render", "YouTube")
BRAND_RE = re.compile(r"\b(" + "|".join(BRANDS) + r")\b")
URL_RE = re.compile(r"\S+\.(com|org|io|dev)\S*")
MODE_PILLS = {"mock": "LIVE · Demo data", "sandbox": "LIVE · PayPal Sandbox"}


def load_scenes(path: Path = SCENES_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def facts() -> dict[str, str]:
    """Prices and terms for narration ({fact:key}) and the slides: the same numbers as the app's intro (D-015)."""
    try:
        from app.config import load_settings
        from app.routes.landing import landing_view
    except ImportError:  # run from demo-video/ without the repo root on sys.path
        import sys
        sys.path.insert(0, str(ROOT))
        from app.config import load_settings
        from app.routes.landing import landing_view
    return {k: str(v) for k, v in landing_view(load_settings()).items() if isinstance(v, (str, int))}


def resolve(text: str, *, spoken: bool = False, today: datetime | None = None,
            fact_values: dict[str, str] | None = None) -> str:
    """{on:N} -> the calendar date N days after a sign-up made today ("Nov 18"; spoken "November 18"), same rule as
    scripts/ui_check.on(). {fact:key} -> the app's own number (landing_view), e.g. {fact:intro} -> "$24.99"."""
    now = today or datetime.now(UTC)

    def on(m: re.Match[str]) -> str:
        d = now + timedelta(days=int(m.group(1)))
        return f"{d:%B} {d.day}" if spoken else f"{d:%b} {d.day}"
    text = ON_RE.sub(on, text)
    if FACT_RE.search(text):
        values = fact_values if fact_values is not None else facts()
        text = FACT_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    return text


def plain(text: str) -> str:
    """Narration without the *accent* markup."""
    return text.replace("*", "")


def tokens(text: str) -> list[tuple[str, bool]]:
    """Words of a (resolved) narration with their accent flag. *word* or *several words* is accented (D-184)."""
    out, accent = [], False
    for raw in text.split():
        m = ACCENT_RE.fullmatch(raw)
        start, word, end = (bool(m[1]), m[2] + m[4], bool(m[3])) if m else (False, raw, False)
        if start:
            accent = True
        out.append((word, accent))
        if end:
            accent = False
    return [(w, a) for w, a in out if w]


def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def words(text: str) -> int:
    return len(re.findall(r"\S+", plain(text)))


def brands(text: str) -> list[str]:
    return BRAND_RE.findall(URL_RE.sub("", plain(text)))


def mode_pill(health: dict[str, Any]) -> str:
    """The frame's pill, read from the running app's /healthz (never typed by hand)."""
    mode = health.get("mode")
    if mode not in MODE_PILLS:
        raise ValueError(f"/healthz reported mode {mode!r}; expected mock or sandbox")
    return MODE_PILLS[mode]


class Slot(BaseModel):
    """One scene on the final timeline."""
    id: str
    kind: str
    start: float
    duration: float


def timeline(d: dict[str, Any], mode: str) -> list[Slot]:
    """Scenes in order with their start in the final video. Outside sandbox mode a "paypal" scene is dropped and
    its seconds go to its "mock_fallback" scene, so the total stays the same and nothing is faked."""
    extra: dict[str, float] = {}
    for s in d["scenes"]:
        if s["kind"] == "paypal" and mode != "sandbox":
            extra[s["mock_fallback"]] = extra.get(s["mock_fallback"], 0) + s["duration"]
    out, t = [], 0.0
    for s in d["scenes"]:
        if s["kind"] == "paypal" and mode != "sandbox":
            continue
        dur = float(s["duration"] + extra.get(s["id"], 0))
        out.append(Slot(id=s["id"], kind=s["kind"], start=round(t, 3), duration=dur))
        t += dur
    return out


CUT_KEEP = 1.2  # seconds of a "cut" wait left on screen, so the viewer sees it start (e.g. the review spinner)
CUT_TAIL = 0.3  # and its last moment, just before the result appears


def cut_span(t0: float, t1: float) -> tuple[float, float] | None:
    """The stretch of a "cut": true action (recording seconds t0..t1) the build jumps over, or None if it's short."""
    a, b = t0 + CUT_KEEP, t1 - CUT_TAIL
    return (round(a, 3), round(b, 3)) if b - a >= 0.5 else None


def segments(start: float, end: float, cuts: list[list[float]], duration: float) -> list[tuple[float, float, float]]:
    """(source start, offset in the scene, length) of a recorded scene with its cuts jumped over, trimmed to the
    scene's duration (never extended)."""
    out, src, off = [], start, 0.0
    for a, b in [*sorted((float(x), float(y)) for x, y in cuts), (end, end)]:
        length = min(a - src, duration - off)
        if length > 0:
            out.append((round(src, 3), round(off, 3), round(length, 3)))
            off += length
        src = max(src, b)
        if off >= duration:
            break
    return out


def scene_time(t: float, start: float, cuts: list[list[float]]) -> float:
    """A recording time as seconds into the edited scene (a time inside a cut maps to where the cut is)."""
    removed = 0.0
    for a, b in sorted((float(x), float(y)) for x, y in cuts):
        if t >= b:
            removed += b - a
        elif t > a:
            return round(a - start - removed, 3)
    return round(t - start - removed, 3)


def total_seconds(d: dict[str, Any]) -> int:
    return sum(s["duration"] for s in d["scenes"])


def chapters(d: dict[str, Any], slots: list[Slot]) -> list[dict[str, Any]]:
    """[{name, start, end}] in order of first appearance; the stage's progress bar draws one segment each."""
    by_id = {s["id"]: s for s in d["scenes"]}
    out: list[dict[str, Any]] = []
    for slot in slots:
        name = by_id[slot.id]["chapter"]
        if out and out[-1]["name"] == name:
            out[-1]["end"] = slot.start + slot.duration
        else:
            out.append({"name": name, "start": slot.start, "end": slot.start + slot.duration})
    return out


def chunks(n_words: int, texts: list[str], max_words: int = 14) -> list[list[int]]:
    """Split a scene's words into headline chunks of at most `max_words`: whole phrases (ending in punctuation)
    are packed together, and a sentence end starts a new chunk once it has 5 words. Old chunks scroll away."""
    phrases: list[list[int]] = [[]]
    for i in range(n_words):
        phrases[-1].append(i)
        if texts[i][-1:] in ".,;:?!" or len(phrases[-1]) == max_words:
            phrases.append([])
    out: list[list[int]] = [[]]
    for ph in (p for p in phrases if p):
        if out[-1] and len(out[-1]) + len(ph) > max_words:
            out.append([])
        out[-1] += ph
        if texts[ph[-1]][-1:] in ".?!" and len(out[-1]) >= 5:
            out.append([])
    return [c for c in out if c]


def cue_times(cues: list[dict[str, str]], word_rows: list[dict[str, Any]]) -> list[tuple[str, float | None]]:
    """(element id, seconds into the scene) for each cue: the first word matching the cue word after the previous
    cue's word, so a repeated word cues in order. None if the word isn't found (check_scenes reports it)."""
    out, after = [], 0
    for cue in cues:
        want, hit = norm(cue["word"]), None
        for i in range(after, len(word_rows)):
            if norm(word_rows[i]["w"]) == want:
                hit, after = i, i + 1
                break
        out.append((cue["show"], None if hit is None else float(word_rows[hit]["start"])))
    return out


def video_script_md(d: dict[str, Any]) -> str:
    rows = ["# SubGuard demo video script", "",
            f"Generated from `demo-video/scenes.json` by `check_scenes.py`. Total {total_seconds(d)} s "
            f"(cap {d['max_total_seconds']} s), {d['words_per_minute']} wpm voice-over. *Accent* words show in the "
            "accent colour in the word-by-word headline.", "",
            "| Time | Scene | Kind | Kicker | Shows | Voice-over (= headline) |", "|---|---|---|---|---|---|"]
    t = 0
    for s in d["scenes"]:
        start, t = t, t + s["duration"]
        if s["kind"] in RECORDED:
            shows = "; ".join(a["action"] + (f" `{a.get('target') or a.get('url')}`" if a.get("target") or a.get("url")
                                             else "") + (" (masked)" if a.get("text") == "{demo_password}" else "")
                              for a in s.get("actions", []))
        else:
            shows = f"{s['kind']} `{s.get('slide') or s['id']}`" + (
                " · cues " + ", ".join(f"{c['word']}→{c['show']}" for c in s.get("cues", [])) if s.get("cues") else "")
        notes = [n for n, on in (("**pending**", s.get("pending")), ("sandbox only; in mock mode its time goes to "
                 f"{s.get('mock_fallback')}", s["kind"] == "paypal")) if on]
        rows.append(f"| {start // 60}:{start % 60:02d}-{t // 60}:{t % 60:02d} | {s['id']} | {s['kind']} | "
                    f"`{s['kicker']}` | {shows}{' (' + '; '.join(notes) + ')' if notes else ''} | "
                    f"{resolve(s['narration'])} |")
    return "\n".join(rows) + "\n"


def srt(entries: list[tuple[float, float, str]]) -> str:
    def ts(x: float) -> str:
        ms = round(x * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "".join(f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(entries, 1))


def captions(d: dict[str, Any], slots: list[Slot], voice_seconds: dict[str, float]) -> str:
    """Narration subtitles (out/captions.srt, for the upload) on the real timeline, each while its voice plays."""
    by_id = {s["id"]: s for s in d["scenes"]}
    return srt([(x.start, x.start + min(voice_seconds.get(x.id, x.duration), x.duration),
                 plain(resolve(by_id[x.id]["narration"]))) for x in slots if by_id[x.id]["narration"].strip()])


def probe_seconds(path: Path) -> float:
    """Media duration via ffprobe (the hard cap is checked on the real file, not on the plan)."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe isn't installed or not on PATH (it comes with ffmpeg: https://ffmpeg.org)")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout.strip()
    return float(out)

"""Validate scenes.json v2 (D-184). Returns (errors, warnings); check_scenes.py prints them, the tests assert them.

A "pending": true scene only warns: its actions may be placeholders.
The password is never written in scenes.json: a `type` into login-password must use "{demo_password}" (the recorder
fills it in from DEMO_PASSWORD), and that placeholder goes nowhere else.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from videolib import (
    HARD_LIMIT_SECONDS,
    KINDS,
    RECORDED,
    ROOT,
    STAGE_HTML,
    SUB_RE,
    brands,
    cue_times,
    plain,
    resolve,
    tokens,
    words,
)

ACTIONS = {"goto", "click", "hover", "type", "press", "wait_for", "wait", "scroll_to", "highlight"}
SETUPS = {"reset", "day", "subscribe", "signed_out"}
PASSWORD = "{demo_password}"  # filled in by record_demo.py; the password field is masked
PASSWORD_FIELD = "login-password"
CHAPTERS = ("Title", "Problem", "How it works", "Live product", "Close")
ID_RE = re.compile(r"\d\d[a-z]?_[a-z0-9_]+")
TOP = ("title", "base_url", "app_viewport", "stage", "voice", "words_per_minute", "max_total_seconds", "links",
       "scenes")
SCENE = ("id", "kind", "chapter", "kicker", "duration", "narration")


def stage_ids(html: str) -> set[str]:
    return set(re.findall(r"""\bid=["']([^"']+)["']""", html))


def _zoom(sid: str, z: dict[str, Any], duration: int, vp: dict[str, int], hole: list[int]) -> list[str]:
    errors = []
    rect = z.get("rect")
    if not (isinstance(rect, list) and len(rect) == 4 and all(isinstance(v, (int, float)) for v in rect)):
        return [f"{sid}: zoom.rect must be [x, y, w, h] in app_viewport pixels"]
    x, y, w, h = rect
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > vp["width"] or y + h > vp["height"]:
        errors.append(f"{sid}: zoom.rect {rect} is outside the {vp['width']}x{vp['height']} recording")
    if abs(w / h - hole[2] / hole[3]) > 0.02 * hole[2] / hole[3]:
        errors.append(f"{sid}: zoom.rect must have the frame's aspect ratio {hole[2]}:{hole[3]}")
    at, dur = z.get("at", -1), z.get("dur", 0)
    if at < 0 or dur < 1.6 or at + dur > duration:
        errors.append(f"{sid}: zoom needs at >= 0, dur >= 1.6 s (0.8 s in, 0.8 s out) and at + dur <= {duration} s")
    return errors


def _actions(sid: str, s: dict[str, Any]) -> list[str]:
    errors = []
    made = {s["setup"]["subscribe"]} if s.get("setup", {}).get("subscribe") else set()
    for a in s.get("actions", []):
        if a.get("action") not in ACTIONS:
            errors.append(f"{sid}: unknown action {a.get('action')!r}")
        if a.get("action") == "type" and a.get("target") == PASSWORD_FIELD and a.get("text") != PASSWORD:
            errors.append(f"{sid}: type into {PASSWORD_FIELD} must use \"{PASSWORD}\" (never the password itself)")
        if PASSWORD in str(a) and not (a.get("action") == "type" and a.get("target") == PASSWORD_FIELD):
            errors.append(f"{sid}: {PASSWORD} only goes in a type into {PASSWORD_FIELD} (a masked field)")
        if "cut" in a and (a["cut"] is not True or a.get("action") not in ("goto", "wait_for")):
            errors.append(f"{sid}: \"cut\": true only goes on a goto or wait_for (a live wait the build jumps over)")
        for key in SUB_RE.findall(a.get("url", "")):
            if key not in made:
                errors.append(f"{sid}: {{sub:{key}}} needs \"setup\": {{\"subscribe\": \"{key}\"}}")
    if set(s.get("setup", {})) - SETUPS:
        errors.append(f"{sid}: setup keys must be in {sorted(SETUPS)}")
    return errors


def validate(d: dict[str, Any], root: Path = ROOT, stage_html: str | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = [f"scenes.json: missing '{k}'" for k in TOP if k not in d]
    warnings: list[str] = []
    if errors:
        return errors, warnings
    cap, wpm = d["max_total_seconds"], d["words_per_minute"]
    hole, vp = d["stage"].get("hole", [0, 0, 16, 9]), d["app_viewport"]
    if cap >= HARD_LIMIT_SECONDS:
        errors.append(f"max_total_seconds {cap} must stay under {HARD_LIMIT_SECONDS} (3 minutes)")
    total = sum(s.get("duration", 0) for s in d["scenes"] if isinstance(s.get("duration"), int))
    if total > cap:
        errors.append(f"total {total} s is over max_total_seconds {cap}")
    if abs(vp["width"] / vp["height"] - hole[2] / hole[3]) > 0.01:
        errors.append("app_viewport and stage.hole must have the same aspect ratio (no stretching)")
    if not d["links"].get("hosted"):
        warnings.append("links.hosted is empty: the end card shows no hosted URL (fill it after the Render deploy)")
    stage_path = root / STAGE_HTML.relative_to(ROOT)
    if stage_html is None:
        stage_html = stage_path.read_text(encoding="utf-8") if stage_path.exists() else ""
    ids = stage_ids(stage_html)  # empty (no stage file under `root`): the element checks are skipped
    seen: set[str] = set()
    chapter_at = 0
    by_id = {s.get("id"): s for s in d["scenes"]}
    for s in d["scenes"]:
        sid = s.get("id", "?")
        missing = [k for k in SCENE if k not in s]
        if missing:
            errors.append(f"{sid}: missing {', '.join(missing)}")
            continue
        if not ID_RE.fullmatch(sid):
            errors.append(f"{sid}: id must look like 01_name")
        if sid in seen:
            errors.append(f"{sid}: duplicate id")
        seen.add(sid)
        kind, duration = s["kind"], s["duration"]
        if kind not in KINDS:
            errors.append(f"{sid}: kind must be one of {', '.join(KINDS)}")
        if s["chapter"] not in CHAPTERS or CHAPTERS.index(s["chapter"]) < chapter_at:
            errors.append(f"{sid}: chapter must be one of {CHAPTERS}, in that order")
        else:
            chapter_at = CHAPTERS.index(s["chapter"])
        if not isinstance(duration, int) or duration <= 0:
            errors.append(f"{sid}: duration must be a positive whole number of seconds")
            continue
        spoken = resolve(s["narration"], spoken=True)
        if words(spoken) > duration * wpm / 60:
            errors.append(f"{sid}: {words(spoken)} words don't fit {duration} s at {wpm} wpm")
        for b in sorted(set(brands(s["narration"]) + brands(s["kicker"]))):
            errors.append(f"{sid}: real brand {b!r} in the narration or kicker (CLAUDE.md: no real brands)")
        if PASSWORD in s["narration"] or PASSWORD in s["kicker"]:
            errors.append(f"{sid}: no password in the narration or kicker")
        if s["narration"].count("*") % 2:
            errors.append(f"{sid}: unbalanced *accent* markup")
        rows = [{"w": w, "start": float(i)} for i, (w, _) in enumerate(tokens(resolve(s["narration"])))]
        for show, at in cue_times(s.get("cues", []), rows):
            if at is None:
                errors.append(f"{sid}: a cue word for {show!r} isn't in the narration (in cue order)")
            if ids and show not in ids:
                errors.append(f"{sid}: cue element #{show} isn't in stage/stage.html")
        if kind in ("slide", "card"):
            if ids and f"slide-{s.get('slide')}" not in ids:
                errors.append(f"{sid}: needs \"slide\" naming a <section id=\"slide-...\"> in stage/stage.html")
            if s.get("actions"):
                errors.append(f"{sid}: a {kind} scene has no actions (it's drawn by the stage)")
        if kind in RECORDED:
            errors += _actions(sid, s)
            if not s.get("actions") and not s.get("pending"):
                errors.append(f"{sid}: needs at least one action")
            if s.get("zoom"):
                errors += _zoom(sid, s["zoom"], duration, vp, hole)
        if kind == "paypal":
            fb = by_id.get(s.get("mock_fallback"))
            if not fb or fb.get("kind") != "app":
                errors.append(f"{sid}: \"mock_fallback\" must name an app scene (it gets this scene's time in mock)")
            for a in s.get("actions", []):
                if a.get("action") == "goto" and not a["url"].startswith(("{paypal_autopay}", "https://www.sandbox.")):
                    errors.append(f"{sid}: a paypal scene only opens PayPal sandbox pages, got {a['url']!r}")
        if s.get("pending"):
            warnings.append(f"{sid}: pending (placeholder actions and narration until its step fills it in)")
        if plain(s["kicker"]) != s["kicker"] or not s["kicker"].startswith("//"):
            errors.append(f"{sid}: kicker must start with // and have no markup")
    return errors, warnings


def missing_targets(d: dict[str, Any], ui_source: str) -> list[str]:
    """App-scene action targets with no data-testid in the UI source (templates, scripts, rendered pages)."""
    out = []
    for s in d["scenes"]:
        if s.get("kind") != "app":
            continue
        for a in s.get("actions", []):
            t = a.get("target")
            if not t or t.startswith(("finding-", "status-")):
                continue
            if not re.search(rf"""data-testid="{re.escape(t)}"|["'`]{re.escape(t)}["'`]""", ui_source):
                msg = f"{s['id']}: target {t!r} not found in the UI"
                out.append(msg + " (pending scene)" if s.get("pending") else msg)
    return out

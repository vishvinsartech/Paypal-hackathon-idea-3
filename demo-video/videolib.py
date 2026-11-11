"""Shared demo-video logic (no ffmpeg, no browser): validate scenes.json, plan the final cut, write VIDEO_SCRIPT.md.

Used by check_scenes.py, build_video.py and tests/test_video_tooling.py. A scene with "type": "clip" is a manually
recorded clip (demo-video/clips/, gitignored): it has no actions, is at most `max_clip_seconds` long, and the
build inserts it at its position, trimmed to its duration (D-114).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
SCENES_PATH = ROOT / "demo-video" / "scenes.json"
HARD_LIMIT_SECONDS = 180  # the hackathon's "under 3 minutes"; scenes.json keeps a 5 s margin below it
ACTIONS = {"goto", "click", "hover", "type", "press", "wait_for", "wait", "scroll_to", "highlight"}
ID_RE = re.compile(r"\d\d[a-z]?_[a-z0-9_]+")
ON_RE = re.compile(r"\{on:(\d+)\}")
SUB_RE = re.compile(r"\{sub:([a-z0-9-]+)\}")
SETUPS = {"subscribe"}
# CLAUDE.md "No real brands": captions and narration never name one (PayPal is the platform we build on). URLs are
# stripped first, so the repo link may stay on screen. Email: say "Open in my email app", not the provider.
BRANDS = ("Gmail", "Google", "Outlook", "Yahoo", "Apple", "iCloud", "Microsoft", "Amazon", "Netflix", "Spotify",
          "Adobe", "Notion", "Grammarly", "Evernote", "Slack", "Zapier", "GitHub", "Anthropic", "Claude", "OpenAI",
          "ChatGPT", "GPT", "Render", "YouTube")
BRAND_RE = re.compile(r"\b(" + "|".join(BRANDS) + r")\b")
URL_RE = re.compile(r"\S+\.(com|org|io|dev)\S*")


def load_scenes(path: Path = SCENES_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_clip(scene: dict[str, Any]) -> bool:
    return scene.get("type") == "clip"


def total_seconds(d: dict[str, Any], *, with_clips: bool = True) -> int:
    return sum(s["duration"] for s in d["scenes"] if with_clips or not is_clip(s))


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def resolve(text: str, *, spoken: bool = False, today: datetime | None = None) -> str:
    """{on:N} -> the calendar date N days after a sign-up made today, as SubGuard writes it ("Nov 18"), or the
    spoken form ("November 18") for the voice-over. Same rule as scripts/ui_check.on()."""
    now = today or datetime.now(UTC)

    def sub(m: re.Match[str]) -> str:
        d = now + timedelta(days=int(m.group(1)))
        return f"{d:%B} {d.day}" if spoken else f"{d:%b} {d.day}"
    return ON_RE.sub(sub, text)


def brands(text: str) -> list[str]:
    return BRAND_RE.findall(URL_RE.sub("", text))


def validate(d: dict[str, Any], root: Path = ROOT) -> tuple[list[str], list[str]]:
    """(errors, warnings). A missing clip file is only a warning: the mock build skips that scene."""
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("title", "viewport", "voice", "words_per_minute", "max_total_seconds", "scenes"):
        if key not in d:
            errors.append(f"scenes.json: missing '{key}'")
    if errors:
        return errors, warnings
    cap = d["max_total_seconds"]
    if cap >= HARD_LIMIT_SECONDS:
        errors.append(f"max_total_seconds {cap} must stay under {HARD_LIMIT_SECONDS} (3 minutes)")
    total = total_seconds(d)
    if total > cap:
        errors.append(f"total {total} s is over max_total_seconds {cap} (clips included)")
    wpm, max_clip = d["words_per_minute"], d.get("max_clip_seconds", 15)
    seen: set[str] = set()
    for s in d["scenes"]:
        sid = s.get("id", "?")
        if not ID_RE.fullmatch(sid):
            errors.append(f"{sid}: id must look like 01_name or 03b_name")
        if sid in seen:
            errors.append(f"{sid}: duplicate id")
        seen.add(sid)
        for key in ("duration", "on_screen", "narration", "actions"):
            if key not in s:
                errors.append(f"{sid}: missing '{key}'")
        if not isinstance(s.get("duration"), int) or s.get("duration", 0) <= 0:
            errors.append(f"{sid}: duration must be a positive whole number of seconds")
            continue
        spoken = resolve(s.get("narration", ""), spoken=True)
        if words(spoken) > s["duration"] * wpm / 60:
            errors.append(f"{sid}: {words(spoken)} words don't fit {s['duration']} s at {wpm} wpm")
        for b in sorted(set(brands(s.get("on_screen", "")) + brands(s.get("narration", "")))):
            errors.append(f"{sid}: real brand {b!r} in the caption or narration (CLAUDE.md: no real brands)")
        if s.get("setup") and (set(s["setup"]) - SETUPS or not s.get("separate")):
            errors.append(f"{sid}: setup must be one of {sorted(SETUPS)} on a \"separate\": true scene")
        if is_clip(s):
            clip = s.get("clip", "")
            if not clip.startswith("demo-video/clips/"):
                errors.append(f"{sid}: clip must live in demo-video/clips/ (gitignored), got {clip!r}")
            if s["duration"] > max_clip:
                errors.append(f"{sid}: clip scene is {s['duration']} s; the limit is {max_clip} s")
            if s.get("actions"):
                errors.append(f"{sid}: a clip scene has no actions")
            if clip and not (root / clip).exists():
                warnings.append(f"{sid}: {clip} is missing; record it (demo-video/README.md). A mock build "
                                "skips this scene.")
        else:
            if not s.get("actions"):
                errors.append(f"{sid}: needs at least one action")
            made = {s["setup"]["subscribe"]} if s.get("setup", {}).get("subscribe") else set()
            for a in s.get("actions", []):
                if a.get("action") not in ACTIONS:
                    errors.append(f"{sid}: unknown action {a.get('action')!r}")
                for key in SUB_RE.findall(a.get("url", "")):
                    if key not in made:
                        errors.append(f"{sid}: {{sub:{key}}} needs \"setup\": {{\"subscribe\": \"{key}\"}}")
    return errors, warnings


def missing_targets(d: dict[str, Any], ui_source: str) -> list[str]:
    """Action targets with no data-testid in the UI source (templates, scripts, rendered pages)."""
    out = []
    for s in d["scenes"]:
        for a in s.get("actions", []):
            t = a.get("target")
            if not t or t.startswith(("finding-", "status-")):
                continue
            if not re.search(rf"""data-testid="{re.escape(t)}"|["'`]{re.escape(t)}["'`]""", ui_source):
                out.append(f"{s['id']}: target {t!r} not found in the UI")
    return out


class Segment(BaseModel):
    scene_id: str
    kind: str  # screen | clip
    source: str  # path of the screen recording or the clip
    start: float = 0.0  # where the scene starts in `source`
    duration: float  # trimmed to the scene's duration, never extended


def plan(d: dict[str, Any], timing: dict[str, Any], *, root: Path = ROOT, screen: str = "demo-video/out/screen.webm",
         require_clips: bool = False) -> tuple[list[Segment], list[str]]:
    """The final cut, in scene order: recorded screen segments (from timing.json) with each clip inserted at its
    scene's position and trimmed to its duration. Returns (segments, warnings); raises ValueError on a problem."""
    recorded = {t["id"]: t for t in timing.get("scenes", [])}
    segments: list[Segment] = []
    warnings: list[str] = []
    for s in d["scenes"]:
        if is_clip(s):
            if not (root / s["clip"]).exists():
                if require_clips:
                    raise ValueError(f"{s['id']}: {s['clip']} is missing (--require-clips)")
                warnings.append(f"{s['id']}: {s['clip']} missing; scene skipped")
                continue
            segments.append(Segment(scene_id=s["id"], kind="clip", source=s["clip"], duration=s["duration"]))
            continue
        t = recorded.get(s["id"])
        if t is None:
            raise ValueError(f"{s['id']}: not in timing.json; record the demo again")
        length = min(float(t["end"]) - float(t["start"]), float(s["duration"]))
        segments.append(Segment(scene_id=s["id"], kind="screen", source=screen, start=float(t["start"]),
                                duration=round(length, 3)))
    total = sum(x.duration for x in segments)
    if total > d["max_total_seconds"] or total >= HARD_LIMIT_SECONDS:
        raise ValueError(f"the cut is {total:.1f} s; it must be at most {d['max_total_seconds']} s (under 3 minutes)")
    return segments, warnings


def video_script_md(d: dict[str, Any]) -> str:
    rows = ["# SubGuard demo video script", "", f"Generated from `demo-video/scenes.json` by `check_scenes.py`. "
            f"Total {total_seconds(d)} s (cap {d['max_total_seconds']} s; clips included), "
            f"{d['words_per_minute']} wpm voice-over.", "",
            "| Time | Scene | Caption | Actions | Voice-over |", "|---|---|---|---|---|"]
    t = 0
    for s in d["scenes"]:
        start, t = t, t + s["duration"]
        acts = (f"**clip** `{s['clip']}` (recorded by hand)" if is_clip(s) else
                "; ".join(a["action"] + (f" `{a.get('target') or a.get('url')}`" if a.get("target") or a.get("url")
                                         else "") for a in s["actions"]))
        rows.append(f"| {start // 60}:{start % 60:02d}-{t // 60}:{t % 60:02d} | {s['id']} | "
                    f"{resolve(s['on_screen'])} | {acts} | {resolve(s['narration'])} |")
    return "\n".join(rows) + "\n"


def offsets(segments: list[Segment]) -> dict[str, float]:
    """Where each scene starts in the final cut (a skipped clip shifts everything after it)."""
    out, t = {}, 0.0
    for seg in segments:
        out[seg.scene_id] = round(t, 3)
        t += seg.duration
    return out


def srt(entries: list[tuple[float, float, str]]) -> str:
    def ts(x: float) -> str:
        ms = round(x * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "".join(f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(entries, 1))


def probe_seconds(path: Path) -> float:
    """Media duration via ffprobe (the hard cap is checked on the real file, not on the plan)."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe isn't installed or not on PATH (it comes with ffmpeg: https://ffmpeg.org)")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout.strip()
    return float(out)

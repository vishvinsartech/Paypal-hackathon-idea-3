"""Render the video's stage (`python scripts/tasks.py demo-video-stage`, or `demo-video-preview`).

The stage (demo-video/stage/) is the chrome, the word-by-word headline, the chapter bar, the slides, the cards and,
for app/paypal scenes, the browser frame with a hole for the recording. Every frame is a pure function of time
(stage.js SG.seek), so this steps through the real timeline frame by frame in Playwright and pipes screenshots to
ffmpeg (D-184): sharp text, exact sync, and identical frames are reused instead of re-captured.

- Full (after record_demo.py): the timeline comes from out/timing.json (mode read from /healthz while recording,
  and the real URL of every page the recorder visited) plus out/words.json -> out/stage.mp4 (1920x1080, 30 fps).
- --preview: no app recording needed. Scene durations from scenes.json, a grey placeholder in the hole, the mode
  pill from the running app's /healthz (or "PREVIEW" if it isn't running), 10 fps, half size, with the voice-over
  mixed in -> out/preview.mp4, so you can check the timing with sound in about a minute.
- Sign-in (Phase 7): it first checks DEMO_PASSWORD (environment or .env; a clear error if missing) and, when the
  app is running, signs in as Priya with it, so a stage is never made for an app the recorder can't get into.
Usage: python demo-video/record_stage.py [--preview] [--base-url URL]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from signin import demo_password, session_cookie  # noqa: E402
from videolib import (  # noqa: E402
    OUT,
    ROOT,
    STAGE_HTML,
    SUB_RE,
    Slot,
    captions,
    chapters,
    chunks,
    cue_times,
    facts,
    load_scenes,
    mode_pill,
    timeline,
)

ESTIMATE_WPM = 150  # only when out/words.json is missing (the preview warns)


def scene_urls(slot: Slot, scene: dict[str, Any], timing: dict[str, Any] | None, base: str,
               carry: str) -> list[dict[str, Any]]:
    """URL bar values for a recorded scene, on the stage timeline. From the recorder's navigation log when there
    is one (the real URL), else (preview) the scene's first goto."""
    if timing is not None:
        rec = next((r for r in timing["scenes"] if r["id"] == slot.id), None)
        if rec is None:
            return [{"t": slot.start, "url": carry}] if carry else []
        log = timing.get("urls", [])
        before = [u["url"] for u in log if u["t"] <= rec["start"]]
        first = before[-1] if before else carry
        out = [{"t": slot.start, "url": first}] if first else []
        out += [{"t": round(slot.start + u["t"] - rec["start"], 3), "url": u["url"]}
                for u in log if rec["start"] < u["t"] < rec["start"] + slot.duration]
        return out
    goto = next((a["url"] for a in scene.get("actions", []) if a["action"] == "goto"), None)
    if goto is None:
        return [{"t": slot.start, "url": carry}] if carry else []
    url = goto if goto.startswith("http") or goto.startswith("{paypal") else base.rstrip("/") + goto
    return [{"t": slot.start, "url": SUB_RE.sub("…", url).replace("{paypal_autopay}", "PayPal sandbox")}]


def estimate_words(scene: dict[str, Any]) -> dict[str, Any]:
    from make_voiceover import spread, word_rows
    from videolib import plain, resolve, tokens
    texts = [w for w, _ in tokens(plain(resolve(scene["narration"], spoken=True)))]
    seconds = min(scene["duration"] - 0.3, len(texts) * 60 / ESTIMATE_WPM)
    return {"id": scene["id"], "seconds": seconds, "words": word_rows(scene["narration"], spread(len(texts), texts,
                                                                                                  seconds, 0.2))}


def stage_data(d: dict[str, Any], words: dict[str, Any], mode: str, pill: str, *, timing: dict[str, Any] | None,
               preview: bool, fact_values: dict[str, str] | None = None) -> dict[str, Any]:
    slots = timeline(d, mode)
    by_id = {s["id"]: s for s in d["scenes"]}
    by_words = {w["id"]: w for w in words.get("scenes", [])}
    base = (timing or {}).get("base_url") or d["base_url"]
    out, carry = [], ""
    for slot in slots:
        s = by_id[slot.id]
        rows = (by_words.get(slot.id) or estimate_words(s))["words"]
        texts = [r["w"] for r in rows]
        lines = [[{"w": rows[i]["w"], "a": rows[i]["a"], "t": round(slot.start + rows[i]["start"], 3)} for i in c]
                 for c in chunks(len(rows), texts)]
        cues = [{"id": show, "t": round(slot.start + at, 3)} for show, at in cue_times(s.get("cues", []), rows)
                if at is not None]
        urls = scene_urls(slot, s, timing, base, carry) if slot.kind in ("app", "paypal") else []
        carry = urls[-1]["url"] if urls else carry
        out.append({"id": slot.id, "kind": slot.kind, "slide": s.get("slide"), "start": slot.start,
                    "dur": slot.duration, "kicker": s["kicker"], "chunks": lines, "cues": cues, "urls": urls})
    total = sum(x.duration for x in slots)
    return {"fps": d["stage"]["fps"], "total": total, "preview": preview, "pill": pill,
            "facts": fact_values if fact_values is not None else facts(), "links": d["links"],
            "chapters": chapters(d, slots), "slots": out}


def render(data: dict[str, Any], output: Path, *, fps: int, preview: bool) -> int:
    """Step the stage frame by frame into ffmpeg. Returns the number of screenshots taken."""
    from playwright.sync_api import sync_playwright
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg isn't installed or not on PATH (https://ffmpeg.org/download.html)")
    enc = ["-vf", "scale=960:540", "-crf", "30"] if preview else ["-crf", "16"]
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps),
                           "-c:v", "mjpeg", "-i", "-", *enc, "-c:v", "libx264", "-preset", "veryfast",
                           "-pix_fmt", "yuv420p", "-r", str(fps), str(output)], stdin=subprocess.PIPE)
    assert ff.stdin is not None
    shots, frames = 0, int(round(data["total"] * fps))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(STAGE_HTML.as_uri())
        page.evaluate("document.fonts.ready.then(() => true)")
        page.evaluate("d => SG.init(d)", data)
        last_key, img = None, b""
        started = time.monotonic()
        for i in range(frames):
            key = page.evaluate("t => SG.seek(t)", i / fps)
            if key != last_key:
                img = page.screenshot(type="jpeg", quality=70 if preview else 92)
                last_key, shots = key, shots + 1
            ff.stdin.write(img)
            if i % (fps * 10) == 0:
                print(f"  {i / fps:6.1f}s / {data['total']:.0f}s  ({time.monotonic() - started:.0f} s)", flush=True)
        browser.close()
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit("ffmpeg failed while encoding the stage")
    return shots


def health(base: str) -> dict[str, Any] | None:
    try:
        return httpx.get(base.rstrip("/") + "/healthz", timeout=5).json()
    except (httpx.HTTPError, ValueError):
        return None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d = load_scenes()
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="fast low-quality stage + voice, no app recording")
    ap.add_argument("--base-url", default=d["base_url"])
    args = ap.parse_args()
    password = demo_password()  # exits with a clear message when DEMO_PASSWORD isn't set
    if health(args.base_url) is not None:
        session_cookie(args.base_url, password)  # exits clearly if the running app rejects it
        print(f"signed in to {args.base_url} as Priya")
    words_path, timing_path = OUT / "words.json", OUT / "timing.json"
    words = json.loads(words_path.read_text(encoding="utf-8")) if words_path.exists() else {}
    if not words:
        print("WARNING no out/words.json (run make_voiceover.py): word timings are estimated at 150 wpm")
    if args.preview:
        h, timing = health(args.base_url), None
        mode = (h or {}).get("mode", "mock")
        pill = mode_pill(h) if h else "PREVIEW · app not running"
    else:
        if not timing_path.exists():
            print("No out/timing.json yet: run record_demo.py first (or use --preview).")
            return 1
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
        mode, pill = timing["mode"], mode_pill({"mode": timing["mode"]})
    data = stage_data(d, words, mode, pill, timing=timing, preview=args.preview)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stage.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    fps = 10 if args.preview else data["fps"]
    target = OUT / ("preview_video.mp4" if args.preview else "stage.mp4")
    started = time.monotonic()
    shots = render(data, target, fps=fps, preview=args.preview)
    print(f"stage: {data['total']:.0f} s, {shots} screenshots, {time.monotonic() - started:.0f} s -> "
          f"{target.relative_to(ROOT)} ({mode} mode, pill {pill!r})")
    if not args.preview:
        return 0
    from build_video import mix_command, voice_inputs
    vo_path = OUT / "voiceover.json"
    vo = json.loads(vo_path.read_text(encoding="utf-8")) if vo_path.exists() else {"scenes": []}
    slots = timeline(d, mode)
    output = OUT / "preview.mp4"
    subprocess.run(mix_command(target, output, voice_inputs(slots, vo), total=data["total"]), check=True, cwd=ROOT)
    (OUT / "captions.srt").write_text(captions(d, slots, {r["id"]: r["seconds"] for r in vo["scenes"]}),
                                      encoding="utf-8")
    print(f"preview with voice-over: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

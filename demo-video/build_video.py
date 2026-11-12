"""Build the final video (`make demo-video`, last step): the stage, the app recording in its hole, the voice-over.

Inputs (demo-video/out/):
- stage.mp4 from record_stage.py: the whole timeline (chrome, headline, slides, cards, the browser frame)
- screen.webm + timing.json from record_demo.py ({"mode", "base_url", "scenes": [{"id", "start", "end"}], "urls"})
- voiceover.json from make_voiceover.py (optional: without it the video is silent)

For every app/paypal scene its stretch of screen.webm (from timing.json) is cut, trimmed to the scene's duration
(never extended), given the scene's optional slow zoom (zoompan: in 0.8 s, hold, out 0.8 s), scaled into the
stage's hole and overlaid there at the scene's place on the timeline (an overlay, no chromakey). Each voice is
delayed to its scene's start (adelay) and mixed with normalize=0; --music <licensed file> at volume 0.08.
H.264 -preset veryfast -crf 20, AAC, +faststart, trimmed to 178 s at most; then ffprobe checks the file is under
180 s and within max_total_seconds, otherwise it's deleted and the build fails. Also writes out/captions.srt.
Usage: python demo-video/build_video.py [--music FILE] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import HARD_LIMIT_SECONDS, OUT, RECORDED, ROOT, Slot, captions, load_scenes, probe_seconds, timeline  # noqa: E402

FPS = 30
TRIM_SECONDS = 178  # hard trim; ffprobe then checks < 180
MUSIC_VOLUME = 0.08
RAMP = 0.8  # zoom in / out seconds


class Overlay(BaseModel):
    scene_id: str
    at: float        # where it starts in the final video
    src_start: float  # where it starts in screen.webm
    duration: float   # trimmed to the scene, never extended
    zoom: dict[str, Any] | None = None


def plan(d: dict[str, Any], timing: dict[str, Any]) -> tuple[list[Slot], list[Overlay]]:
    """The timeline for the recorded mode and one overlay per recorded scene. Raises ValueError on a problem."""
    slots = timeline(d, timing["mode"])
    rec = {t["id"]: t for t in timing.get("scenes", [])}
    by_id = {s["id"]: s for s in d["scenes"]}
    overlays = []
    for slot in slots:
        if slot.kind not in RECORDED:
            continue
        t = rec.get(slot.id)
        if t is None:
            raise ValueError(f"{slot.id}: not in timing.json; record the demo again")
        length = min(float(t["end"]) - float(t["start"]), slot.duration)
        overlays.append(Overlay(scene_id=slot.id, at=slot.start, src_start=float(t["start"]),
                                duration=round(length, 3), zoom=by_id[slot.id].get("zoom")))
    total = sum(s.duration for s in slots)
    if total > d["max_total_seconds"] or total >= HARD_LIMIT_SECONDS:
        raise ValueError(f"the cut is {total:.1f} s; it must be at most {d['max_total_seconds']} s (under 3 minutes)")
    return slots, overlays


def zoom_filter(z: dict[str, Any], vp: dict[str, int]) -> str:
    """zoompan into rect [x, y, w, h] (recording pixels): eased in over 0.8 s from `at`, held, out by at + dur."""
    x, y, w, _ = z["rect"]
    a, b, n = z["at"], z["at"] + z["dur"], f"(in/{FPS})"
    q = f"min(clip(({n}-{a})/{RAMP},0,1),clip(({b}-{n})/{RAMP},0,1))"
    e = f"(({q})*({q})*(3-2*({q})))"
    shrink = round(1 - w / vp["width"], 5)
    return (f"zoompan=z='1/(1-{shrink}*{e})':x='{x}*{e}':y='{y}*{e}':d=1:"
            f"s={vp['width']}x{vp['height']}:fps={FPS}")


def voice_inputs(slots: list[Slot], voiceover: dict[str, Any]) -> list[tuple[str, float]]:
    """(file, start in the video) for every scene on the timeline (a skipped paypal scene's voice is dropped)."""
    at = {s.id: s.start for s in slots}
    return [(r["file"], at[r["id"]]) for r in voiceover.get("scenes", []) if r["id"] in at]


def audio_graph(voices: list[tuple[str, float]], first: int, music: str | None) -> tuple[list[str], list[str]]:
    """(extra ffmpeg inputs, filters ending in [aout]) or ([], []) without audio."""
    inputs, filters, labels = [], [], []
    for k, (file, start) in enumerate(voices):
        inputs += ["-i", str(ROOT / file)]
        ms = round(start * 1000)
        filters.append(f"[{first + k}:a]adelay={ms}|{ms}[a{k}]")
        labels.append(f"[a{k}]")
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        filters.append(f"[{first + len(voices)}:a]volume={MUSIC_VOLUME}[music]")
        labels.append("[music]")
    if labels:
        filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest[aout]")
    return inputs, filters


def mix_command(video: Path, output: Path, voices: list[tuple[str, float]], *, total: float,
                music: str | None = None) -> list[str]:
    """Video as is + the voice-over (the preview uses this)."""
    a_in, a_f = audio_graph(voices, 1, music)
    maps = ["-map", "0:v"] + (["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"] if a_f else [])
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), *a_in,
            *(["-filter_complex", ";".join(a_f)] if a_f else []), *maps, "-c:v", "copy",
            "-t", f"{total:.3f}", str(output)]


def ffmpeg_args(d: dict[str, Any], overlays: list[Overlay], total: float, output: Path, *, stage: str, screen: str,
                voices: list[tuple[str, float]] | None = None, music: str | None = None) -> list[str]:
    hx, hy, hw, hh = d["stage"]["hole"]
    vp = d["app_viewport"]
    inputs = ["-i", stage]
    filters, last = [], "[0:v]"
    for k, o in enumerate(overlays, 1):
        inputs += ["-ss", f"{o.src_start:.3f}", "-t", f"{o.duration:.3f}", "-i", screen]
        chain = [f"fps={FPS}", f"scale={vp['width']}:{vp['height']}"]
        if o.zoom:
            chain.append(zoom_filter(o.zoom, vp))
        chain += [f"scale={hw}:{hh}:flags=lanczos", "setsar=1", f"setpts=PTS-STARTPTS+{o.at:.3f}/TB"]
        filters.append(f"[{k}:v]" + ",".join(chain) + f"[s{k}]")
        end = o.at + o.duration
        filters.append(f"{last}[s{k}]overlay=x={hx}:y={hy}:eof_action=pass:"
                       f"enable='between(t,{o.at:.3f},{end:.3f})'[o{k}]")
        last = f"[o{k}]"
    filters.append(f"{last}format=yuv420p[vout]")
    a_in, a_f = audio_graph(voices or [], len(overlays) + 1, music)
    maps = ["-map", "[vout]"] + (["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"] if a_f else [])
    return ["ffmpeg", "-y", *inputs, *a_in, "-filter_complex", ";".join(filters + a_f), *maps,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), "-movflags", "+faststart",
            "-t", f"{min(total, TRIM_SECONDS):.3f}", str(output)]


def verify(output: Path, cap: int) -> str | None:
    """None if the real file is under 3 minutes and within the cap; else the problem."""
    seconds = probe_seconds(output)
    if seconds >= HARD_LIMIT_SECONDS or seconds > cap + 0.5:  # +0.5: container rounding at the last frame
        return f"{output.name} is {seconds:.2f} s; it must be under {HARD_LIMIT_SECONDS} s (cap {cap} s)"
    print(f"ffprobe: {output.name} is {seconds:.2f} s (under {HARD_LIMIT_SECONDS} s)")
    return None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", help="a licensed music file, mixed at volume 0.08")
    ap.add_argument("--dry-run", action="store_true", help="print the cut and the ffmpeg command only")
    args = ap.parse_args()
    timing_path, screen, stage = OUT / "timing.json", OUT / "screen.webm", OUT / "stage.mp4"
    missing = [p.name for p in (timing_path, screen, stage) if not p.exists()]
    if missing:
        print(f"Missing {', '.join(missing)} in demo-video/out/: run record_demo.py (app running), then "
              "record_stage.py, then this again (python scripts/tasks.py demo-video runs them all).")
        return 1
    d = load_scenes()
    try:
        slots, overlays = plan(d, json.loads(timing_path.read_text(encoding="utf-8")))
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 1
    vo_path = OUT / "voiceover.json"
    vo = json.loads(vo_path.read_text(encoding="utf-8")) if vo_path.exists() else {"scenes": []}
    voices = voice_inputs(slots, vo)
    if not voices:
        print("WARNING no voice-over (run make_voiceover.py); the video will be silent")
    for s in slots:
        o = next((x for x in overlays if x.scene_id == s.id), None)
        extra = f" recording {o.src_start:6.1f}s +{o.duration:.1f}s{' zoom' if o.zoom else ''}" if o else ""
        print(f"  {s.start:6.1f}s  {s.id:<18} {s.kind:<6} {s.duration:5.1f}s{extra}")
    total = sum(s.duration for s in slots)
    print(f"total {total:.1f} s (cap {d['max_total_seconds']} s)")
    (OUT / "captions.srt").write_text(captions(d, slots, {r["id"]: r["seconds"] for r in vo["scenes"]}),
                                      encoding="utf-8")
    output = OUT / "demo.mp4"
    cmd = ffmpeg_args(d, overlays, total, output, stage=str(stage), screen=str(screen), voices=voices,
                      music=args.music)
    if args.dry_run:
        print(" ".join(cmd))
        return 0
    if shutil.which("ffmpeg") is None:
        print("ffmpeg isn't installed or not on PATH (https://ffmpeg.org/download.html).")
        return 1
    subprocess.run(cmd, check=True, cwd=ROOT)
    try:
        problem = verify(output, d["max_total_seconds"])
    except RuntimeError as exc:
        problem = str(exc)
    if problem:
        output.unlink(missing_ok=True)
        print(f"ERROR {problem}")
        return 1
    print(f"wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

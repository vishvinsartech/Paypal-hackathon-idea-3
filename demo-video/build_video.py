"""Cut the demo video (`make demo-video`, last step): screen scenes + hand-recorded clips + voice-over, in order.

Inputs:
- demo-video/out/screen.webm + out/timing.json from record_demo.py
  (timing.json: {"scenes": [{"id": "01_hook", "start": 0.0, "end": 10.1}, ...]}, seconds into screen.webm)
- demo-video/clips/*.mp4 for "type": "clip" scenes (gitignored; see demo-video/README.md)
- demo-video/out/voiceover.json from make_voiceover.py (optional: without it the video is silent)

Each screen scene is trimmed to its scenes.json duration (never extended); each clip is inserted at its scene's
position and trimmed to its duration (max 15 s); a missing clip is skipped with a warning unless --require-clips.
Each scene's voice is delayed to where that scene really starts in the cut (adelay) and mixed with normalize=0.
Optional: --music <licensed file> at volume 0.08, --burn-captions (the on_screen captions, top centre).
H.264 -preset veryfast -crf 20, AAC, +faststart, trimmed to 178 s at most, then ffprobe checks the file is under
180 s (and at most max_total_seconds); otherwise it's deleted and the build fails.
Output: demo-video/out/demo.mp4 (1920x1080, 30 fps).

Usage: python demo-video/build_video.py [--require-clips] [--music FILE] [--burn-captions] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import HARD_LIMIT_SECONDS, ROOT, Segment, load_scenes, offsets, plan, probe_seconds, resolve, srt  # noqa: E402

OUT = ROOT / "demo-video" / "out"
W, H, FPS = 1920, 1080, 30
TRIM_SECONDS = 178  # hard trim; ffprobe then checks < 180
MUSIC_VOLUME = 0.08
TITLES = "demo-video/out/titles.srt"  # relative: ffmpeg runs in ROOT, so the subtitles filter needs no C: escaping
# 2 = bottom centre (SSA numbering), so the shop's "Fictional merchant" banner at the top stays visible
TITLE_STYLE = "Alignment=2,FontName=Arial,FontSize=13,BorderStyle=3,Outline=4,Shadow=0,MarginV=12"


def voice_inputs(segments: list[Segment], voiceover: dict[str, Any]) -> list[tuple[str, float]]:
    """(file, start in the cut) for every scene that made the cut. A skipped clip's voice is dropped too."""
    at = offsets(segments)
    return [(r["file"], at[r["id"]]) for r in voiceover.get("scenes", []) if r["id"] in at]


def titles_srt(segments: list[Segment], d: dict[str, Any]) -> str:
    caption = {s["id"]: resolve(s["on_screen"]) for s in d["scenes"]}
    at = offsets(segments)
    return srt([(at[g.scene_id], at[g.scene_id] + g.duration, caption[g.scene_id]) for g in segments])


def ffmpeg_args(segments: list[Segment], output: Path, voices: list[tuple[str, float]] | None = None,
                music: str | None = None, burn: bool = False) -> list[str]:
    """One ffmpeg call: trim each segment, scale/pad to 1920x1080 at 30 fps, concat in order; mix the voices."""
    inputs: list[str] = []
    filters: list[str] = []
    for i, seg in enumerate(segments):
        inputs += ["-ss", f"{seg.start:.3f}", "-t", f"{seg.duration:.3f}", "-i", str(ROOT / seg.source)]
        filters.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                       f"setsar=1,fps={FPS},format=yuv420p[v{i}]")
    video = "[out]"
    concat = "".join(f"[v{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[out]"
    filters.append(concat)
    if burn:
        filters.append(f"[out]subtitles='{TITLES}':force_style='{TITLE_STYLE}'[vout]")
        video = "[vout]"
    total = sum(s.duration for s in segments)
    audio: list[str] = []
    n = len(segments)
    for k, (file, start) in enumerate(voices or []):
        inputs += ["-i", str(ROOT / file)]
        ms = round(start * 1000)
        filters.append(f"[{n + k}:a]adelay={ms}|{ms}[a{k}]")
        audio.append(f"[a{k}]")
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        filters.append(f"[{n + len(voices or [])}:a]volume={MUSIC_VOLUME}[music]")
        audio.append("[music]")
    maps = ["-map", video]
    if audio:
        filters.append("".join(audio) + f"amix=inputs={len(audio)}:normalize=0:duration=longest[aout]")
        maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
    return ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), *maps,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart",
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
    ap.add_argument("--require-clips", action="store_true")
    ap.add_argument("--music", help="a licensed music file, mixed at volume 0.08")
    ap.add_argument("--burn-captions", action="store_true", help="burn the on_screen captions into the video")
    ap.add_argument("--dry-run", action="store_true", help="print the cut and the ffmpeg command only")
    args = ap.parse_args()
    timing_path, screen = OUT / "timing.json", OUT / "screen.webm"
    if not (timing_path.exists() and screen.exists()):
        print("No screen recording yet (demo-video/out/screen.webm + timing.json). Record it first: "
              "python demo-video/record_demo.py (the app must be running), then run this again.")
        return 1
    d = load_scenes()
    try:
        segments, warnings = plan(d, json.loads(timing_path.read_text(encoding="utf-8")),
                                  require_clips=args.require_clips)
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 1
    vo_path = OUT / "voiceover.json"
    voices = voice_inputs(segments, json.loads(vo_path.read_text(encoding="utf-8"))) if vo_path.exists() else []
    if not voices:
        warnings.append("no voice-over (run make_voiceover.py); the video will be silent")
    for w in warnings:
        print(f"WARNING {w}")
    t = 0.0
    for seg in segments:
        print(f"  {t:6.1f}s  {seg.scene_id:<22} {seg.kind:<6} {seg.duration:5.1f}s  {seg.source}")
        t += seg.duration
    print(f"total {t:.1f} s (cap {d['max_total_seconds']} s)")
    if args.burn_captions:
        (ROOT / TITLES).write_text(titles_srt(segments, d), encoding="utf-8")
    output = OUT / "demo.mp4"
    cmd = ffmpeg_args(segments, output, voices, args.music, args.burn_captions)
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

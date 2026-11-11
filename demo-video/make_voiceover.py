"""Make the voice-over (`python scripts/tasks.py demo-video-voice`): one audio file per scene, never longer than it.

- Your own recording wins: demo-video/audio/<scene_id>.wav or .mp3 (gitignored). Otherwise the scene's narration
  is spoken by edge-tts with scenes.json's voice (en-US-JennyNeural) into demo-video/out/voice/<scene_id>.mp3.
  `{on:N}` dates are spoken in full ("November 18"). Clip scenes get narration too (the clip's own audio is dropped).
- Every file is measured with ffprobe. If one is longer than its scene, it FAILS (the video must not grow): shorten
  the narration in scenes.json, or re-record that scene.
- Writes demo-video/out/voiceover.json ({"scenes": [{"id", "file", "seconds"}]}) for build_video.py, and
  demo-video/out/captions.srt (the narration as subtitles for the full cut, clip included) for the YouTube upload.

Needs ffmpeg/ffprobe on PATH, and `pip install -r demo-video/requirements.txt` (edge-tts) unless every scene has
a recording. Usage: python demo-video/make_voiceover.py [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import ROOT, load_scenes, probe_seconds, resolve, srt  # noqa: E402

AUDIO = ROOT / "demo-video" / "audio"
OUT = ROOT / "demo-video" / "out"
VOICE = OUT / "voice"


def recorded(scene_id: str) -> Path | None:
    return next((p for p in (AUDIO / f"{scene_id}.wav", AUDIO / f"{scene_id}.mp3") if p.exists()), None)


async def speak(text: str, voice: str, path: Path) -> None:
    try:
        import edge_tts
    except ImportError:
        raise SystemExit("edge-tts isn't installed: pip install -r demo-video/requirements.txt (or record "
                         f"demo-video/audio/{path.stem}.wav yourself)") from None
    await edge_tts.Communicate(text, voice).save(str(path))


def check(rows: list[dict[str, Any]], d: dict[str, Any]) -> list[str]:
    """Problems: any voice file longer than its scene (the duration maths, no ffmpeg needed)."""
    dur = {s["id"]: s["duration"] for s in d["scenes"]}
    return [f"{r['id']}: voice-over is {r['seconds']:.2f} s but the scene is {dur[r['id']]} s; shorten the "
            "narration or re-record it" for r in rows if r["seconds"] > dur[r["id"]]]


def captions(rows: list[dict[str, Any]], d: dict[str, Any]) -> str:
    """Narration subtitles over the full cut (every scene, clip included), each shown while its voice plays."""
    start, entries = 0.0, []
    seconds = {r["id"]: r["seconds"] for r in rows}
    for s in d["scenes"]:
        if s["narration"]:
            entries.append((start, start + min(seconds.get(s["id"], s["duration"]), s["duration"]),
                            resolve(s["narration"])))
        start += s["duration"]
    return srt(entries)


async def build(d: dict[str, Any], force: bool) -> list[dict[str, Any]]:
    VOICE.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in d["scenes"]:
        if not s["narration"].strip():
            continue
        path = recorded(s["id"])
        if path is None:
            path = VOICE / f"{s['id']}.mp3"
            if force or not path.exists():
                await speak(resolve(s["narration"], spoken=True), d["voice"], path)
        rows.append({"id": s["id"], "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                     "seconds": round(probe_seconds(path), 3), "source": "recorded" if path.parent == AUDIO else "tts"})
    return rows


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="speak every TTS scene again (after a narration change)")
    args = ap.parse_args()
    d = load_scenes()
    try:
        rows = asyncio.run(build(d, args.force))
    except RuntimeError as exc:  # ffprobe missing
        print(f"ERROR {exc}")
        return 1
    for r in rows:
        print(f"  {r['id']:<22} {r['seconds']:6.2f}s  {r['source']:<8} {r['file']}")
    problems = check(rows, d)
    for p in problems:
        print(f"ERROR {p}")
    if problems:
        return 1
    (OUT / "voiceover.json").write_text(json.dumps({"scenes": rows}, indent=2), encoding="utf-8")
    (OUT / "captions.srt").write_text(captions(rows, d), encoding="utf-8")
    print("wrote demo-video/out/voiceover.json and demo-video/out/captions.srt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

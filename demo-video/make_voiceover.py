"""Make the voice-over and its word timings (`python scripts/tasks.py demo-video-voice`).

- Your own recording wins: demo-video/audio/<scene_id>.wav or .mp3 (gitignored). Its words are spread over the
  clip by word length (there are no word events for a recording).
- Otherwise edge-tts speaks the scene's narration with scenes.json's voice, with boundary="WordBoundary" (edge-tts 7
  sends sentence boundaries by default), and each word gets the time the voice says it. `{on:N}` is spoken in full
  ("November 18"). The audio and its word events are cached in out/voice/ and re-spoken when the text changes.
- Every file is measured with ffprobe. If one is longer than its scene, it FAILS (the video must not grow).
- Writes out/voiceover.json ({"scenes": [{"id", "file", "seconds", "source"}]}) and out/words.json
  ({"scenes": [{"id", "seconds", "words": [{"w", "a", "start", "end"}]}]}, seconds from the scene's start; "w" is
  the headline word as shown, "a" = accent). The build and the preview write out/captions.srt on the real timeline.

Needs ffprobe on PATH and `pip install -r demo-video/requirements.txt` unless every scene has a recording.
Usage: python demo-video/make_voiceover.py [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import OUT, ROOT, load_scenes, norm, plain, probe_seconds, resolve, tokens  # noqa: E402

AUDIO = ROOT / "demo-video" / "audio"
VOICE = OUT / "voice"
TICK = 1e-7  # edge-tts offsets are in 100 ns units


def recorded(scene_id: str) -> Path | None:
    return next((p for p in (AUDIO / f"{scene_id}.wav", AUDIO / f"{scene_id}.mp3") if p.exists()), None)


async def speak(text: str, voice: str, path: Path) -> list[list[Any]]:
    """Write the mp3 and return the word boundaries [[start, end, text], ...] in seconds."""
    try:
        import edge_tts
    except ImportError:
        raise SystemExit("edge-tts isn't installed: pip install -r demo-video/requirements.txt (or record "
                         f"demo-video/audio/{path.stem}.wav yourself)") from None
    marks: list[list[Any]] = []
    with path.open("wb") as f:
        async for chunk in edge_tts.Communicate(text, voice, boundary="WordBoundary").stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] * TICK
                marks.append([round(start, 3), round(start + chunk["duration"] * TICK, 3), chunk["text"]])
    return marks


def spread(n: int, texts: list[str], seconds: float, start: float = 0.0) -> list[tuple[float, float]]:
    """n words over [start, seconds], each in proportion to its length (no word events available)."""
    if n == 0:
        return []
    weights = [len(norm(w)) + 2 for w in texts]
    span = max(seconds - start, 0.0)
    out, t = [], start
    for w in weights:
        d = span * w / sum(weights)
        out.append((round(t, 3), round(t + d, 3)))
        t += d
    return out


def align(texts: list[str], marks: list[list[Any]], seconds: float) -> list[tuple[float, float]]:
    """Give each spoken word a time from the TTS boundaries. One boundary can cover several words ("November 18"):
    its time is split over them. Words after a mismatch are spread over the rest of the clip."""
    times: list[tuple[float, float]] = []
    i = 0
    for start, end, text in marks:
        target = norm(text)
        if not target or i >= len(texts):
            continue
        j, acc = i, ""
        while j < len(texts) and len(acc) < len(target):
            acc += norm(texts[j])
            j += 1
        while j < len(texts) and not norm(texts[j]) and acc == target:  # a lone "—" rides with its word
            j += 1
        if acc != target:
            break
        times += spread(j - i, texts[i:j], end, start)
        i = j
    if len(times) < len(texts):
        times += spread(len(texts) - len(times), texts[len(times):], seconds, times[-1][1] if times else 0.0)
    out, last = [], 0.0
    for a, b in times:  # never go backwards, never past the clip
        a = min(max(a, last), seconds)
        out.append((round(a, 3), round(min(max(b, a), seconds), 3)))
        last = a
    return out


def word_rows(narration: str, times: list[tuple[float, float]]) -> list[dict[str, Any]]:
    shown = tokens(resolve(narration))
    return [{"w": w, "a": a, "start": t[0], "end": t[1]} for (w, a), t in zip(shown, times, strict=False)]


def check(rows: list[dict[str, Any]], d: dict[str, Any]) -> list[str]:
    """Problems: any voice file longer than its scene (the duration maths, no ffmpeg needed)."""
    dur = {s["id"]: s["duration"] for s in d["scenes"]}
    return [f"{r['id']}: voice-over is {r['seconds']:.2f} s but the scene is {dur[r['id']]} s; shorten the "
            "narration or re-record it" for r in rows if r["seconds"] > dur[r["id"]]]


async def build(d: dict[str, Any], force: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    VOICE.mkdir(parents=True, exist_ok=True)
    rows, words_out = [], []
    for s in d["scenes"]:
        if not s["narration"].strip():
            continue
        spoken = plain(resolve(s["narration"], spoken=True))
        texts = [w for w, _ in tokens(spoken)]
        path, marks = recorded(s["id"]), None
        if path is None:
            path, meta = VOICE / f"{s['id']}.mp3", VOICE / f"{s['id']}.json"
            cached = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
            if force or not path.exists() or cached.get("text") != spoken or cached.get("voice") != d["voice"]:
                marks = await speak(spoken, d["voice"], path)
                meta.write_text(json.dumps({"text": spoken, "voice": d["voice"], "marks": marks}), encoding="utf-8")
            else:
                marks = cached["marks"]
        seconds = round(probe_seconds(path), 3)
        times = align(texts, marks, seconds) if marks else spread(len(texts), texts, seconds - 0.1, 0.1)
        rows.append({"id": s["id"], "file": str(path.relative_to(ROOT)).replace("\\", "/"), "seconds": seconds,
                     "source": "tts" if marks is not None else "recorded"})
        words_out.append({"id": s["id"], "seconds": seconds, "words": word_rows(s["narration"], times)})
    return rows, words_out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="speak every TTS scene again")
    args = ap.parse_args()
    d = load_scenes()
    try:
        rows, words_out = asyncio.run(build(d, args.force))
    except RuntimeError as exc:  # ffprobe missing
        print(f"ERROR {exc}")
        return 1
    for r in rows:
        print(f"  {r['id']:<18} {r['seconds']:6.2f}s  {r['source']:<8} {r['file']}")
    problems = check(rows, d)
    for p in problems:
        print(f"ERROR {p}")
    if problems:
        return 1
    (OUT / "voiceover.json").write_text(json.dumps({"scenes": rows}, indent=2), encoding="utf-8")
    (OUT / "words.json").write_text(json.dumps({"scenes": words_out}, indent=1), encoding="utf-8")
    print("wrote demo-video/out/voiceover.json and demo-video/out/words.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""demo-video tooling (D-114): scene validation, the clip insertion plan, the ffmpeg command. No ffmpeg needed."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.config import ROOT_DIR

DV = ROOT_DIR / "demo-video"


def _load(name: str) -> ModuleType:
    if str(DV) not in sys.path:
        sys.path.insert(0, str(DV))
    spec = importlib.util.spec_from_file_location(name, DV / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vl = _load("videolib")
bv = _load("build_video")
SCENES: dict[str, Any] = json.loads((DV / "scenes.json").read_text(encoding="utf-8"))


def timing(d: dict[str, Any], extra: float = 0.0) -> dict[str, Any]:
    """A fake recording: each screen scene recorded back to back, `extra` seconds longer than planned."""
    t, rows = 0.0, []
    for s in d["scenes"]:
        if s.get("type") != "clip":
            rows.append({"id": s["id"], "start": t, "end": t + s["duration"] + extra})
            t += s["duration"] + extra
    return {"scenes": rows}


def with_clip_file(tmp_path: Path) -> Path:
    (tmp_path / "demo-video" / "clips").mkdir(parents=True)
    (tmp_path / "demo-video" / "clips" / "paypal_approval.mp4").write_bytes(b"fake")
    return tmp_path


def test_scenes_json_is_valid_and_a_missing_clip_is_only_a_warning(tmp_path: Path) -> None:
    errors, warnings = vl.validate(SCENES, root=tmp_path)  # tmp root: the clip file is missing
    assert errors == []
    assert len(warnings) == 1 and "03b_paypal_approval" in warnings[0] and "skips" in warnings[0]
    assert vl.validate(SCENES, root=with_clip_file(tmp_path)) == ([], [])
    assert vl.total_seconds(SCENES) <= SCENES["max_total_seconds"] <= 175 < vl.HARD_LIMIT_SECONDS


@pytest.mark.parametrize(("change", "problem"), [
    (lambda d: d["scenes"][3].update(duration=20), "limit is 15 s"),
    (lambda d: d["scenes"][3].update(actions=[{"action": "click", "target": "brand"}]), "has no actions"),
    (lambda d: d["scenes"][3].update(clip="clips/x.mp4"), "demo-video/clips/"),
    (lambda d: d.update(max_total_seconds=180), "under 180"),
    (lambda d: d["scenes"][0].update(duration=40), "over max_total_seconds"),
    (lambda d: d["scenes"][1].update(narration="word " * 40), "don't fit"),
])
def test_validation_catches_problems(change: Any, problem: str, tmp_path: Path) -> None:
    d = copy.deepcopy(SCENES)
    assert d["scenes"][3]["type"] == "clip"
    change(d)
    errors, _ = vl.validate(d, root=tmp_path)
    assert any(problem in e for e in errors), errors


def test_plan_inserts_the_clip_at_its_scene_and_trims_everything(tmp_path: Path) -> None:
    root = with_clip_file(tmp_path)
    segments, warnings = vl.plan(SCENES, timing(SCENES, extra=2.5), root=root)
    assert warnings == []
    assert [s.scene_id for s in segments] == [s["id"] for s in SCENES["scenes"]]
    clip = segments[3]
    assert (clip.kind, clip.source, clip.duration) == ("clip", "demo-video/clips/paypal_approval.mp4", 15)
    for seg, scene in zip(segments, SCENES["scenes"], strict=True):
        assert seg.duration == scene["duration"]  # recordings 2.5 s too long are trimmed, never extended
    assert sum(s.duration for s in segments) == vl.total_seconds(SCENES) <= 175


def test_mock_build_runs_without_the_clip(tmp_path: Path) -> None:
    segments, warnings = vl.plan(SCENES, timing(SCENES), root=tmp_path)
    assert "03b_paypal_approval" not in [s.scene_id for s in segments] and "skipped" in warnings[0]
    with pytest.raises(ValueError, match="require-clips"):
        vl.plan(SCENES, timing(SCENES), root=tmp_path, require_clips=True)


def test_plan_refuses_a_cut_over_the_cap(tmp_path: Path) -> None:
    d = copy.deepcopy(SCENES)
    d["scenes"][0]["duration"] = 60  # validate() would also flag this; plan() enforces it on its own too
    with pytest.raises(ValueError, match="under 3 minutes"):
        vl.plan(d, timing(d), root=with_clip_file(tmp_path))
    with pytest.raises(ValueError, match="timing.json"):
        vl.plan(SCENES, {"scenes": []}, root=tmp_path)


def test_ffmpeg_command_keeps_scene_order(tmp_path: Path) -> None:
    segments, _ = vl.plan(SCENES, timing(SCENES), root=with_clip_file(tmp_path))
    cmd = bv.ffmpeg_args(segments, tmp_path / "out.mp4")
    inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
    assert len(inputs) == len(segments) and inputs[3].endswith("paypal_approval.mp4")
    assert f"concat=n={len(segments)}:v=1:a=0" in cmd[cmd.index("-filter_complex") + 1]
    assert cmd[cmd.index("-t", cmd.index("-t") + 1) + 1] == f"{segments[1].duration:.3f}"


def test_video_script_lists_the_clip() -> None:
    md = vl.video_script_md(SCENES)
    assert "03b_paypal_approval" in md and "**clip** `demo-video/clips/paypal_approval.mp4`" in md
    assert md.count("\n| ") == len(SCENES["scenes"]) + 1  # header + one row per scene


# ---- v3 Phase 5 (V1-V3): the new beats, dates, brands, recorder setup, voice-over and the final mix ----------

vo = _load("make_voiceover")
rd = _load("record_demo")
V1 = [("01_hook", 10), ("02_shop", 15), ("03_companion", 25), ("03b_paypal_approval", 15), ("04_ai_vs_basic", 15),
      ("05_checkin", 15), ("06_cancel", 30), ("07_audit", 15), ("08_proof_scale", 20), ("09_close", 10)]


def test_scenes_follow_the_v3_beats() -> None:
    assert [(s["id"], s["duration"]) for s in SCENES["scenes"]] == V1
    assert vl.total_seconds(SCENES) == 170 <= SCENES["max_total_seconds"] == 175
    quill = SCENES["scenes"][4]
    assert quill["separate"] and quill["setup"] == {"subscribe": "quillnote-plus"}
    assert SCENES["scenes"][2]["sandbox_subscribe"] == "penwright-pro"


def test_dates_resolve_like_the_app() -> None:
    from datetime import UTC, datetime
    day0 = datetime(2026, 11, 11, tzinfo=UTC)
    assert vl.resolve("Act by {on:7} (the terms allow {on:8})", today=day0) == "Act by Nov 18 (the terms allow Nov 19)"
    assert vl.resolve("act by {on:7}", spoken=True, today=day0) == "act by November 18"
    assert "{on:" not in vl.video_script_md(SCENES)


def test_no_real_brands_in_captions_or_narration(tmp_path: Path) -> None:
    for s in SCENES["scenes"]:
        assert vl.brands(s["on_screen"]) == [] and vl.brands(s["narration"]) == [], s["id"]
    assert vl.brands("github.com/someone/repo") == []  # the repo URL may be on screen
    d = copy.deepcopy(SCENES)
    d["scenes"][6]["narration"] = "Open it in Gmail."
    errors, _ = vl.validate(d, root=tmp_path)
    assert any("real brand 'Gmail'" in e for e in errors)


@pytest.mark.parametrize(("change", "problem"), [
    (lambda d: d["scenes"][4].pop("separate"), "setup must be one of"),
    (lambda d: d["scenes"][4].update(setup={"buy": "x"}), "setup must be one of"),
    (lambda d: d["scenes"][1]["actions"].append({"action": "goto", "url": "/subscriptions/{sub:quillnote-plus}"}),
     "needs \"setup\""),
])
def test_setup_and_sub_placeholders_are_checked(change: Any, problem: str, tmp_path: Path) -> None:
    d = copy.deepcopy(SCENES)
    change(d)
    errors, _ = vl.validate(d, root=tmp_path)
    assert any(problem in e for e in errors), errors


def test_separate_scene_keeps_its_place_in_the_cut(tmp_path: Path) -> None:
    """04 is recorded last (after Day 11) but the cut follows scenes.json; voices follow the real cut offsets."""
    rec = {"scenes": [{"id": i, "start": 100.0 + n * 20, "end": 100.0 + n * 20 + dur}
                      for n, (i, dur) in enumerate(V1) if i != "03b_paypal_approval"]}
    segs, _ = vl.plan(SCENES, rec, root=tmp_path)  # no clip file: skipped
    at = vl.offsets(segs)
    assert at["04_ai_vs_basic"] == 50.0 and at["05_checkin"] == 65.0 and "03b_paypal_approval" not in at
    voices = bv.voice_inputs(segs, {"scenes": [{"id": i, "file": f"v/{i}.mp3", "seconds": 1.0} for i, _ in V1]})
    assert ("v/04_ai_vs_basic.mp3", 50.0) in voices and all("03b" not in f for f, _ in voices)
    with_clip = vl.offsets(vl.plan(SCENES, rec, root=with_clip_file(tmp_path))[0])
    assert with_clip["03b_paypal_approval"] == 50.0 and with_clip["04_ai_vs_basic"] == 65.0


def test_final_mix_command(tmp_path: Path) -> None:
    segs, _ = vl.plan(SCENES, timing(SCENES), root=with_clip_file(tmp_path))
    cmd = bv.ffmpeg_args(segs, tmp_path / "demo.mp4", [("v/01.mp3", 0.0), ("v/06.mp3", 95.0)], "m.mp3", burn=True)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "adelay=95000|95000" in graph and "amix=inputs=3:normalize=0" in graph and "volume=0.08" in graph
    assert "subtitles='demo-video/out/titles.srt'" in graph and cmd[cmd.index("-map") + 1] == "[vout]"
    assert cmd[cmd.index("-preset") + 1] == "veryfast" and "+faststart" in cmd
    assert float(cmd[-2]) == 170.0 <= bv.TRIM_SECONDS < vl.HARD_LIMIT_SECONDS
    assert "Real PayPal sandbox approval" in bv.titles_srt(segs, SCENES)


def test_ffprobe_check_rejects_a_long_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bv, "probe_seconds", lambda p: 180.2)
    assert "must be under 180" in (bv.verify(tmp_path / "demo.mp4", 175) or "")
    monkeypatch.setattr(bv, "probe_seconds", lambda p: 170.04)
    assert bv.verify(tmp_path / "demo.mp4", 175) is None


def test_voiceover_never_longer_than_its_scene() -> None:
    rows = [{"id": "01_hook", "seconds": 9.8}, {"id": "02_shop", "seconds": 15.4}]
    problems = vo.check(rows, SCENES)
    assert len(problems) == 1 and problems[0].startswith("02_shop: voice-over is 15.40 s but the scene is 15 s")
    subs = vo.captions(rows, SCENES)
    assert subs.startswith("1\n00:00:00,000 --> 00:00:09,800\nSubGuard reads the fine print")
    assert "00:00:10,000 --> 00:00:25,000" in subs


def test_sandbox_recording_needs_the_pre_approved_subscriptions(tmp_path: Path) -> None:
    path = tmp_path / "sandbox_ids.json"
    path.write_text(json.dumps({"demo_subscriptions": {"penwright-pro": "I-1"}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="quillnote-plus.*--demo-subs"):
        rd.sandbox_ids(path, SCENES)
    path.write_text(json.dumps({"demo_subscriptions": {"penwright-pro": "I-1", "quillnote-plus": "I-2"}}),
                    encoding="utf-8")
    assert rd.sandbox_ids(path, SCENES)["quillnote-plus"] == "I-2"

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

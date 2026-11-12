"""demo-video tooling v2 (D-184): scenes.json v2, word timings, the stage timeline, the overlay build. No ffmpeg."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT_DIR

DV = ROOT_DIR / "demo-video"


def _load(name: str) -> ModuleType:
    if str(DV) not in sys.path:
        sys.path.insert(0, str(DV))
    spec = importlib.util.spec_from_file_location(name, DV / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # pydantic resolves the module's annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


vl = _load("videolib")
sc = _load("schema")
vo = _load("make_voiceover")
rd = _load("record_demo")
rs = _load("record_stage")
bv = _load("build_video")
SCENES: dict[str, Any] = json.loads((DV / "scenes.json").read_text(encoding="utf-8"))
BOARD = [("01_title", "card", 6), ("02_problem", "slide", 16), ("03_problem_cost", "slide", 14),
         ("04_how", "slide", 22), ("05_signin", "app", 10), ("06_shop", "app", 22), ("07_approve", "app", 12),
         ("08_checkin", "app", 20), ("09_proof_app", "app", 14), ("10_ai_vs_basic", "app", 15),
         ("11_paypal_proof", "paypal", 10), ("12_pillars", "slide", 8), ("13_end", "card", 6)]
FACTS = {"intro": "$24.99", "step_up": "$49.99", "trial_days": "10", "notice_days": "3", "intro_months": "3"}


def scene(d: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in d["scenes"] if s["id"] == sid)


def fake_words(d: dict[str, Any]) -> dict[str, Any]:
    """What make_voiceover writes, without TTS: each scene's words spread over 80 % of the scene."""
    out = []
    for s in d["scenes"]:
        texts = [w for w, _ in vl.tokens(vl.plain(vl.resolve(s["narration"], spoken=True)))]
        times = vo.spread(len(texts), texts, s["duration"] * 0.8, 0.1)
        out.append({"id": s["id"], "seconds": s["duration"] * 0.8, "words": vo.word_rows(s["narration"], times)})
    return {"scenes": out}


def fake_timing(d: dict[str, Any], mode: str, extra: float = 0.0) -> dict[str, Any]:
    """A recording made back to back, `extra` seconds longer per scene than planned."""
    t, rows, urls = 2.0, [], []
    for slot in vl.timeline(d, mode):  # the recorder holds each scene for its time on this mode's timeline
        rows.append({"id": slot.id, "start": t, "end": t + slot.duration + extra})
        if slot.kind == "app":
            urls.append({"t": t + 0.2, "url": f"http://127.0.0.1:8000/{slot.id}"})
        t += slot.duration + extra + 1.0  # a second of off-screen setup between scenes
    return {"mode": mode, "base_url": "http://127.0.0.1:8000", "scenes": rows, "urls": urls}


# ---- the v2 schema -------------------------------------------------------------------------------------------

def test_scenes_json_is_valid_v2_and_follows_the_storyboard() -> None:
    errors, warnings = sc.validate(SCENES)
    assert errors == []
    assert not any("pending" in w for w in warnings) and any("links.hosted" in w for w in warnings)
    assert [(s["id"], s["kind"], s["duration"]) for s in SCENES["scenes"]] == BOARD
    assert vl.total_seconds(SCENES) == 175 == SCENES["max_total_seconds"] < vl.HARD_LIMIT_SECONDS
    assert all(s["kicker"].startswith("//") for s in SCENES["scenes"])
    assert [c["name"] for c in vl.chapters(SCENES, vl.timeline(SCENES, "sandbox"))] == list(sc.CHAPTERS)
    assert scene(SCENES, "11_paypal_proof")["mock_fallback"] == "09_proof_app"


@pytest.mark.parametrize(("change", "problem"), [
    (lambda d: scene(d, "02_problem").update(kind="movie"), "kind must be one of"),
    (lambda d: scene(d, "02_problem")["cues"].append({"word": "zebra", "show": "pb-cards"}), "cue word"),
    (lambda d: scene(d, "02_problem")["cues"].append({"word": "Priya", "show": "nope"}), "#nope isn't in stage"),
    (lambda d: scene(d, "12_pillars").update(slide="gone"), "slide-..."),
    (lambda d: scene(d, "04_how").update(chapter="Title"), "in that order"),
    (lambda d: scene(d, "03_problem_cost").update(narration="word " * 40), "don't fit"),
    (lambda d: scene(d, "01_title").update(duration=12), "over max_total_seconds"),
    (lambda d: d.update(max_total_seconds=180), "under 180"),
    (lambda d: scene(d, "06_shop")["zoom"].update(rect=[1400, 700, 640, 360]), "outside"),
    (lambda d: scene(d, "06_shop")["zoom"].update(rect=[0, 0, 640, 640]), "aspect ratio"),
    (lambda d: scene(d, "06_shop")["zoom"].update(at=20), "at + dur"),
    (lambda d: scene(d, "11_paypal_proof")["actions"].insert(0, {"action": "goto", "url": "/shop"}), "PayPal sandbox"),
    (lambda d: scene(d, "11_paypal_proof").pop("mock_fallback"), "mock_fallback"),
    (lambda d: scene(d, "12_pillars").update(actions=[{"action": "wait", "seconds": 1}]), "has no actions"),
    (lambda d: scene(d, "08_checkin").update(narration="Open it in Gmail."), "real brand 'Gmail'"),
    (lambda d: scene(d, "08_checkin").update(setup={"buy": 1}), "setup keys"),
    (lambda d: scene(d, "07_approve")["actions"].append({"action": "goto", "url": "/subscriptions/{sub:x}"}),
     "needs \"setup\""),
    (lambda d: scene(d, "12_pillars").update(narration="*AI reads the fine print."), "unbalanced"),
])
def test_validation_catches_problems(change: Any, problem: str) -> None:
    d = copy.deepcopy(SCENES)
    change(d)
    errors, _ = sc.validate(d)
    assert any(problem in e for e in errors), errors


def test_pending_scenes_warn_but_do_not_fail() -> None:
    d = copy.deepcopy(SCENES)
    signin = scene(d, "05_signin")
    signin["pending"] = True
    signin["actions"] = [{"action": "click", "target": "login-submit"}]  # a placeholder target
    errors, warnings = sc.validate(d)
    assert errors == [] and any("05_signin: pending" in w for w in warnings)
    assert sc.missing_targets(d, "")[0] == "05_signin: target 'login-submit' not found in the UI (pending scene)"
    signin.pop("pending")
    assert sc.missing_targets(d, "")[0] == "05_signin: target 'login-submit' not found in the UI"
    signin["actions"] = []
    assert any("05_signin: needs at least one action" in e for e in sc.validate(d)[0])


def test_signin_scene_types_a_placeholder_not_the_password() -> None:
    s = scene(SCENES, "05_signin")
    assert "pending" not in s and s["setup"] == {"signed_out": True}
    assert [a.get("target") or a.get("url") for a in s["actions"]] == [
        "/", "intro-signin", "login-email", "login-password", "login-submit", "hi-name"]
    typed = {a["target"]: a["text"] for a in s["actions"] if a["action"] == "type"}
    assert typed == {"login-email": "priya@subguard-demo.example", "login-password": "{demo_password}"}
    d = copy.deepcopy(SCENES)
    next(a for a in scene(d, "05_signin")["actions"] if a.get("target") == "login-password")["text"] = "hunter2"
    assert any("must use \"{demo_password}\"" in e for e in sc.validate(d)[0])
    d = copy.deepcopy(SCENES)
    scene(d, "05_signin")["actions"][2]["text"] = "{demo_password}"  # into the (visible) email field
    assert any("only goes in a type into login-password" in e for e in sc.validate(d)[0])
    d = copy.deepcopy(SCENES)
    scene(d, "05_signin")["narration"] += " {demo_password}"
    assert any("no password in the narration" in e for e in sc.validate(d)[0])


def test_check_scenes_finds_a_leaked_password(tmp_path: Path) -> None:
    cs = _load("check_scenes")
    (tmp_path / "demo-video").mkdir()
    (tmp_path / "demo-video" / "VIDEO_SCRIPT.md").write_text("type `login-password`", encoding="utf-8")
    assert cs.password_leaks("s3cret-pw", tmp_path) == []
    (tmp_path / "demo-video" / "scenes.json").write_text('{"text": "s3cret-pw"}', encoding="utf-8")
    assert cs.password_leaks("s3cret-pw", tmp_path) == ["the password appears in demo-video/scenes.json"]


def test_accent_markup_is_parsed() -> None:
    day0 = datetime(2026, 11, 12, tzinfo=UTC)
    text = vl.resolve("Act by *{on:7}*; the *terms allow* it. *SubGuard*: done", today=day0)
    assert vl.tokens(text) == [("Act", False), ("by", False), ("Nov", True), ("19;", True), ("the", False),
                               ("terms", True), ("allow", True), ("it.", False), ("SubGuard:", True), ("done", False)]
    assert vl.plain("*a* b") == "a b" and vl.words("*ten days free*.") == 3
    assert vl.resolve("{fact:intro}/month", fact_values=FACTS) == "$24.99/month"
    assert vl.resolve("act by {on:4}", spoken=True, today=day0) == "act by November 16"


def test_every_cue_word_is_in_its_narration_in_order() -> None:
    for s in SCENES["scenes"]:
        rows = [{"w": w, "start": float(i)} for i, (w, _) in enumerate(vl.tokens(vl.resolve(s["narration"])))]
        hits = vl.cue_times(s.get("cues", []), rows)
        assert all(at is not None for _, at in hits), s["id"]
        assert [at for _, at in hits] == sorted(at for _, at in hits), s["id"]
    rows = [{"w": w, "start": float(i)} for i, w in enumerate("PayPal pays PayPal".split())]
    assert vl.cue_times([{"word": "PayPal", "show": "a"}, {"word": "PayPal", "show": "b"}], rows) == [("a", 0.0),
                                                                                                    ("b", 2.0)]


# ---- word timings ------------------------------------------------------------------------------------------

def test_tts_word_timings_follow_the_boundaries_and_stay_inside_the_clip() -> None:
    texts = "Act by November 18, the terms allow $24.99 a month.".split()
    marks = [[0.1, 0.4, "Act"], [0.41, 0.5, "by"], [0.51, 1.55, "November 18"], [1.69, 1.79, "the"],
             [1.8, 2.1, "terms"], [2.11, 2.35, "allow"], [2.36, 4.5, "$24.99"], [4.52, 4.57, "a"], [4.59, 5.0, "month"]]
    times = vo.align(texts, marks, 5.9)
    assert len(times) == len(texts)
    assert times[0] == (0.1, 0.4) and 0.51 <= times[2][0] < times[3][0] < 1.55 <= times[4][0]
    starts = [a for a, _ in times]
    assert starts == sorted(starts) and all(0 <= a <= b <= 5.9 for a, b in times)
    broken = vo.align(texts, [[0.1, 0.4, "Act"], [0.5, 0.9, "zzz"]], 5.9)  # mismatch: the rest is spread
    assert len(broken) == len(texts) and broken[0] == (0.1, 0.4) and broken[-1][1] <= 5.9


def test_recorded_audio_words_are_spread_and_word_rows_keep_display_and_accent() -> None:
    times = vo.spread(4, ["a", "bb", "ccc", "dddd"], 9.9, 0.1)
    assert times[0][0] == 0.1 and abs(times[-1][1] - 9.9) < 0.01
    assert [a for a, _ in times] == sorted(a for a, _ in times)
    rows = vo.word_rows("Act by *{on:7}*", vo.spread(4, ["Act", "by", "November", "19"], 2.0))
    assert [r["w"] for r in rows][:2] == ["Act", "by"] and [r["a"] for r in rows] == [False, False, True, True]
    for s in fake_words(SCENES)["scenes"]:  # every scene: increasing, inside its scene
        dur = scene(SCENES, s["id"])["duration"]
        starts = [w["start"] for w in s["words"]]
        assert starts == sorted(starts) and all(0 <= w["start"] <= w["end"] <= dur for w in s["words"]), s["id"]


def test_voiceover_never_longer_than_its_scene() -> None:
    rows = [{"id": "01_title", "seconds": 5.8}, {"id": "02_problem", "seconds": 16.4}]
    problems = vo.check(rows, SCENES)
    assert len(problems) == 1 and problems[0].startswith("02_problem: voice-over is 16.40 s but the scene is 16 s")


# ---- the timeline, the stage, the mode pill ----------------------------------------------------------------

def test_mock_drops_the_paypal_scene_and_gives_its_time_to_the_proof_scene() -> None:
    mock, sandbox = vl.timeline(SCENES, "mock"), vl.timeline(SCENES, "sandbox")
    assert "11_paypal_proof" not in [s.id for s in mock] and len(sandbox) == 13
    assert next(s for s in mock if s.id == "09_proof_app").duration == 24
    assert sum(s.duration for s in mock) == sum(s.duration for s in sandbox) == 175
    assert [s.start for s in sandbox][:3] == [0, 6, 22]


def test_mode_pill_comes_from_healthz(client: TestClient) -> None:
    assert vl.mode_pill(client.get("/healthz").json()) == "LIVE · Demo data"
    assert vl.mode_pill({"mode": "sandbox"}) == "LIVE · PayPal Sandbox"
    with pytest.raises(ValueError):
        vl.mode_pill({"mode": "production"})


def test_headline_chunks_are_short_whole_phrases() -> None:
    texts = [w for w, _ in vl.tokens(vl.resolve(scene(SCENES, "04_how")["narration"]))]
    parts = vl.chunks(len(texts), texts)
    assert sum(len(c) for c in parts) == len(texts) and all(len(c) <= 14 for c in parts)
    assert all(texts[c[-1]][-1] in ".,;:?!" for c in parts)  # no chunk ends mid-phrase
    assert vl.chunks(20, ["w"] * 20) == [list(range(14)), list(range(14, 20))]


def test_stage_data_puts_words_cues_and_real_urls_on_the_timeline() -> None:
    timing = fake_timing(SCENES, "mock")
    data = rs.stage_data(SCENES, fake_words(SCENES), "mock", "LIVE · Demo data", timing=timing, preview=False,
                         fact_values=FACTS)
    slots = {s["id"]: s for s in data["slots"]}
    assert data["total"] == 175 and data["pill"] == "LIVE · Demo data" and "11_paypal_proof" not in slots
    shop = slots["06_shop"]
    first = shop["chunks"][0][0]
    assert first["w"] == "Priya" and first["t"] == round(shop["start"] + 0.1, 3)
    assert shop["urls"][-1]["url"] == "http://127.0.0.1:8000/06_shop" and shop["urls"][0]["t"] == shop["start"]
    assert slots["05_signin"]["urls"][0]["url"] == "http://127.0.0.1:8000/05_signin"
    cues = slots["02_problem"]["cues"]
    assert [c["id"] for c in cues][:2] == ["pb-priya", "pb-checkout"]
    assert all(slots["02_problem"]["start"] <= c["t"] < slots["03_problem_cost"]["start"] for c in cues)
    preview = rs.stage_data(SCENES, {}, "mock", "PREVIEW", timing=None, preview=True, fact_values=FACTS)
    assert {s["id"]: s for s in preview["slots"]}["06_shop"]["urls"][0]["url"] == "http://127.0.0.1:8000/shop/penwright"


def test_stage_html_has_every_slide_and_cue_element() -> None:
    ids = sc.stage_ids((DV / "stage" / "stage.html").read_text(encoding="utf-8"))
    for s in SCENES["scenes"]:
        if s["kind"] in ("slide", "card"):
            assert f"slide-{s['slide']}" in ids, s["id"]
        assert {c["show"] for c in s.get("cues", [])} <= ids, s["id"]
    assert {"kicker", "headline", "frame", "hole", "url", "pill-text", "progress"} <= ids


# ---- recording and build -----------------------------------------------------------------------------------

def test_build_overlays_each_recorded_scene_trimmed_into_the_hole() -> None:
    slots, overlays = bv.plan(SCENES, fake_timing(SCENES, "mock", extra=2.5))
    assert [o.scene_id for o in overlays] == ["05_signin", "06_shop", "07_approve", "08_checkin", "09_proof_app",
                                              "10_ai_vs_basic"]
    at = {s.id: s for s in slots}
    for o in overlays:
        assert o.at == at[o.scene_id].start and o.duration == at[o.scene_id].duration  # trimmed, never extended
    assert at["09_proof_app"].duration == 24
    voices = bv.voice_inputs(slots, {"scenes": [{"id": s[0], "file": f"v/{s[0]}.mp3"} for s in BOARD]})
    assert ("v/11_paypal_proof.mp3", 0.0) not in voices and ("v/06_shop.mp3", at["06_shop"].start) in voices
    cmd = bv.ffmpeg_args(SCENES, overlays, 175, Path("demo.mp4"), stage="stage.mp4", screen="screen.webm",
                         voices=voices, music="m.mp3")
    graph = cmd[cmd.index("-filter_complex") + 1]
    hx, hy, hw, hh = SCENES["stage"]["hole"]
    assert graph.count(f"overlay=x={hx}:y={hy}") == len(overlays) and f"scale={hw}:{hh}" in graph
    assert graph.count("zoompan=") == 1 and "chromakey" not in graph and "volume=0.08" in graph
    assert f"adelay={round(at['06_shop'].start * 1000)}" in graph and "normalize=0" in graph
    assert cmd[cmd.index("-preset") + 1] == "veryfast" and "+faststart" in cmd and float(cmd[-2]) == 175.0
    sandbox = bv.plan(SCENES, fake_timing(SCENES, "sandbox"))[1]
    assert sandbox[-1].scene_id == "11_paypal_proof"
    with pytest.raises(ValueError, match="timing.json"):
        bv.plan(SCENES, {"mode": "mock", "scenes": []})


def test_zoom_eases_in_and_out_of_the_rect() -> None:
    z = bv.zoom_filter({"at": 1.0, "rect": [740, 40, 640, 360], "dur": 4.5}, SCENES["app_viewport"])
    assert z.startswith("zoompan=z='1/(1-0.6*") and "s=1600x900" in z and "(in/30)-1.0)/0.8" in z
    assert "(5.5-(in/30))/0.8" in z and "x='740*" in z and "y='40*" in z


def test_ffprobe_check_rejects_a_long_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bv, "probe_seconds", lambda p: 180.2)
    assert "must be under 180" in (bv.verify(tmp_path / "demo.mp4", 175) or "")
    monkeypatch.setattr(bv, "probe_seconds", lambda p: 175.04)
    assert bv.verify(tmp_path / "demo.mp4", 175) is None


def test_sandbox_recording_needs_the_pre_approved_subscriptions(tmp_path: Path) -> None:
    path = tmp_path / "sandbox_ids.json"
    path.write_text(json.dumps({"demo_subscriptions": {"penwright-pro": "I-1"}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="quillnote-plus.*--demo-subs"):
        rd.sandbox_ids(path, SCENES)
    path.write_text(json.dumps({"demo_subscriptions": {"penwright-pro": "I-1", "quillnote-plus": "I-2"}}),
                    encoding="utf-8")
    assert rd.sandbox_ids(path, SCENES)["quillnote-plus"] == "I-2"


def test_highlight_is_a_yellow_glow_and_captions_follow_the_timeline() -> None:
    assert "#f5b942" in rd.HIGHLIGHT_JS and "boxShadow" in rd.HIGHLIGHT_JS and "#14b8a6" not in rd.HIGHLIGHT_JS
    slots = vl.timeline(SCENES, "mock")
    subs = vl.captions(SCENES, slots, {"01_title": 5.0})
    assert subs.startswith("1\n00:00:00,000 --> 00:00:05,000\nSubGuard: AI reads") and "*" not in subs


def test_video_script_lists_every_scene() -> None:
    md = vl.video_script_md(SCENES)
    assert md.count("\n| ") == len(SCENES["scenes"]) + 1 and "{on:" not in md
    assert "**pending**" not in md and "sandbox only" in md
    assert "type `login-password` (masked)" in md and "{demo_password}" not in md
    d = copy.deepcopy(SCENES)
    scene(d, "05_signin")["pending"] = True
    assert "**pending**" in vl.video_script_md(d)

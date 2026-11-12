"""demo-video/scenes.json v2 stays under 3 minutes and only uses selectors the UI really has (spec 13, D-184).

The full `check_scenes.py` also checks the stage and the running app; this is the static part.
"""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from app.config import ROOT_DIR

SCENES = json.loads((ROOT_DIR / "demo-video" / "scenes.json").read_text(encoding="utf-8"))
ACTIONS = {"goto", "click", "hover", "type", "press", "wait_for", "wait", "scroll_to", "highlight"}


def _ui_sources(client: TestClient) -> str:
    """Rendered pages (static test ids) + the scripts that render the rest."""
    pages = [client.get(u).text for u in ("/", "/?demo=1", "/shop", "/shop/penwright", "/shop/penwright/terms")]
    scripts = [f.read_text(encoding="utf-8") for f in (ROOT_DIR / "app" / "static").glob("*.js")]
    # Priya's card, check-in and proof render only later in the story, so their template source counts too.
    templates = [f.read_text(encoding="utf-8") for f in (ROOT_DIR / "app" / "templates").glob("*.html")]
    shop = [f.read_text(encoding="utf-8") for f in (*(ROOT_DIR / "shop" / "static").glob("*.js"),
                                                    *(ROOT_DIR / "shop" / "templates").glob("*.html"))]
    stories = [(ROOT_DIR / "app" / "routes" / "story_card.py").read_text(encoding="utf-8")]  # card button ids
    return "\n".join(pages + scripts + templates + shop + stories)  # the same sources as check_scenes.py


def test_total_under_the_cap_and_narration_fits() -> None:
    assert SCENES["max_total_seconds"] <= 175
    total = sum(s["duration"] for s in SCENES["scenes"])
    assert total <= SCENES["max_total_seconds"] < 180, total
    wpm = SCENES["words_per_minute"]
    for s in SCENES["scenes"]:  # {on:N} is spoken as two words ("November 18")
        words = len(re.findall(r"\S+", re.sub(r"\{on:\d+\}", "Month D", s["narration"])))
        assert words <= s["duration"] * wpm / 60, (s["id"], words)


def test_no_hand_recorded_clip_and_recordings_stay_out_of_git() -> None:
    """D-184: the PayPal proof is recorded in a sandbox take; nothing is spliced in by hand."""
    assert all(s.get("type") != "clip" for s in SCENES["scenes"])
    paypal = [s for s in SCENES["scenes"] if s["kind"] == "paypal"]
    assert len(paypal) == 1 and paypal[0]["mock_fallback"] == "09_proof_app"
    gitignore = (ROOT_DIR / ".gitignore").read_text(encoding="utf-8")
    assert "demo-video/out/" in gitignore and "*.mp4" in gitignore


def test_scenes_tell_the_v3_story() -> None:
    text = json.dumps(SCENES)
    assert "Act by *{on:7}* (the terms allow {on:8})" in text  # D6/D-132 wording, calendar dates, never "Day 7"
    assert "Quillnote" in text and "seventy-two hours" in text and "ai-vs-basic" in text and "{on:4}" in text
    assert "audit-chain" in text and "email-clause" in text and "alert-cancel" in text
    assert "$" not in "".join(s["narration"] for s in SCENES["scenes"])  # prices come from the app (D-015)
    for gone in ("chat-open", "chat-send", "subs-grid", "kpi-patterns"):  # chat is not in the video (D-112)
        assert gone not in text, gone
    for gone in ("Framewise", "Lumen", "John", "add-on", "872.76", "$19", "yearly"):
        assert gone not in text, gone


def test_every_action_is_known_and_every_target_exists(client: TestClient) -> None:
    src = _ui_sources(client)
    for s in SCENES["scenes"]:
        assert re.fullmatch(r"\d\d[a-z]?_[a-z0-9_]+", s["id"]) and s["kicker"].startswith("//")
        if s["kind"] in ("card", "slide"):
            assert not s.get("actions"), s["id"]  # drawn by the stage
            continue
        assert s["actions"] or s.get("pending"), s["id"]
        for a in s["actions"]:
            assert a["action"] in ACTIONS, (s["id"], a)
            target = a.get("target")
            if target and s["kind"] == "app" and not s.get("pending"):
                assert re.search(rf"""data-testid="{re.escape(target)}"|["'`]{re.escape(target)}["'`]""", src) or \
                    target.startswith(("finding-", "status-")), (s["id"], target)

"""demo-video/scenes.json stays under 3 minutes and only uses selectors the UI really has (spec 13).

The full `check_scenes.py` (milestone 9) also visits the running app; this is the static part.
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
    pages = [client.get(u).text for u in ("/?demo=1", "/user", "/shop", "/shop/penwright", "/shop/penwright/terms")]
    scripts = [f.read_text(encoding="utf-8") for f in (ROOT_DIR / "app" / "static").glob("*.js")]
    # Priya's card, check-in and proof banner render only later in the story, so their template source counts too.
    templates = [f.read_text(encoding="utf-8") for f in (ROOT_DIR / "app" / "templates").glob("*.html")]
    return "\n".join(pages + scripts + templates)


def test_total_under_the_cap_and_narration_fits() -> None:
    assert SCENES["max_total_seconds"] <= 175
    total = sum(s["duration"] for s in SCENES["scenes"])
    assert total <= SCENES["max_total_seconds"], total
    wpm = SCENES["words_per_minute"]
    for s in SCENES["scenes"]:
        words = len(re.findall(r"\S+", s["narration"]))
        assert words <= s["duration"] * wpm / 60, (s["id"], words)


def test_scenes_tell_the_simplified_story() -> None:
    text = json.dumps(SCENES)
    assert "$524.88" in text and "Day 7" in text and "Day 11" in text and "email-send" in text
    for gone in ("chat-open", "chat-send", "subs-grid", "kpi-patterns"):  # chat is not in the video (D-112)
        assert gone not in text, gone
    for gone in ("Framewise", "Lumen", "John", "add-on", "872.76", "$19", "yearly"):
        assert gone not in text, gone


def test_every_action_is_known_and_every_target_exists(client: TestClient) -> None:
    src = _ui_sources(client)
    for s in SCENES["scenes"]:
        assert re.fullmatch(r"\d\d_[a-z0-9_]+", s["id"]) and s["on_screen"] and s["actions"]
        for a in s["actions"]:
            assert a["action"] in ACTIONS, (s["id"], a)
            target = a.get("target")
            if target:  # static data-testid="x", or a JS-rendered one ("x" / `x` / x: in the scripts)
                assert re.search(rf"""data-testid="{re.escape(target)}"|["'`]{re.escape(target)}["'`]""", src) or \
                    target.startswith(("finding-", "status-")), (s["id"], target)

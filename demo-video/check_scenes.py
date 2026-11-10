"""Check demo-video/scenes.json without making a video (`make demo-video-check`).

- schema, unique ids, durations, the under-3-minutes cap (clips included), narration at 125 wpm per scene
- every action target is a data-testid the UI has (templates + scripts; with --base-url also the running app)
- clip scenes: the file is in demo-video/clips/ and at most max_clip_seconds; a MISSING clip is only a warning
  (the mock build skips it) unless --require-clips
- writes demo-video/VIDEO_SCRIPT.md
Exit code 1 on any error.

Usage: python demo-video/check_scenes.py [--base-url http://127.0.0.1:8000] [--require-clips]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import ROOT, load_scenes, missing_targets, total_seconds, validate, video_script_md  # noqa: E402

PAGES = ("/?demo=1", "/user", "/shop", "/shop/penwright", "/shop/penwright/terms")


def ui_source(base_url: str | None) -> str:
    files = [*(ROOT / "app" / "templates").glob("*.html"), *(ROOT / "app" / "static").glob("*.js"),
             *(ROOT / "shop" / "templates").glob("*.html"), *(ROOT / "shop" / "static").glob("*.js")]
    parts = [f.read_text(encoding="utf-8") for f in files]
    if base_url:
        parts += [httpx.get(base_url.rstrip("/") + page, timeout=15).text for page in PAGES]
    else:
        parts += rendered_pages()
    return "\n".join(parts)


def rendered_pages() -> list[str]:
    """Render the pages in-process with a throwaway mock app (no server needed; template loops expanded)."""
    data = Path(tempfile.mkdtemp(prefix="subguard-scenes-"))
    shutil.copytree(ROOT / "data" / "seed", data / "seed")
    os.environ["APP_MODE"] = "mock"
    os.environ["DATA_DIR"] = str(data)  # app.main builds a module-level app on import
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(_env_file=None, app_mode="mock", data_dir=data, demo_seed=False)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as client:
        return [client.get(page).text for page in PAGES]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="also check the running app's pages")
    ap.add_argument("--require-clips", action="store_true", help="a missing clip is an error, not a warning")
    args = ap.parse_args()
    d = load_scenes()
    errors, warnings = validate(d)
    errors += missing_targets(d, ui_source(args.base_url))
    if args.require_clips:
        errors += [w for w in warnings if "missing" in w]
        warnings = [w for w in warnings if "missing" not in w]
    out = ROOT / "demo-video" / "VIDEO_SCRIPT.md"
    out.write_text(video_script_md(d), encoding="utf-8")
    print(f"{len(d['scenes'])} scenes, {total_seconds(d)} s with clips / {total_seconds(d, with_clips=False)} s "
          f"without (cap {d['max_total_seconds']} s). Wrote {out.relative_to(ROOT)}.")
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR   {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

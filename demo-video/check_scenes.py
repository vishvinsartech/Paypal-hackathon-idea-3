"""Check demo-video/scenes.json v2 without making a video (`python scripts/tasks.py demo-video-check`).

- schema (kinds, chapters in order, kickers, durations, the cap), narration at 125 wpm per scene, no real brands
- cues: every cue word is in its scene's narration (in order) and every cue / slide element exists in stage.html
- every app-scene action target is a data-testid the UI has (templates + scripts + rendered pages; with --base-url
  the running app's pages instead of an in-process render)
- zoom rects inside the recording and in the frame's aspect ratio; paypal scenes only open PayPal sandbox pages
- sign-in (Phase 7): needs DEMO_PASSWORD (environment or .env; a clear error if missing). With --base-url it signs in
  to the running app with it; it also checks the password is in none of scenes.json, VIDEO_SCRIPT.md,
  out/words.json, out/captions.srt (05_signin types it from the "{demo_password}" placeholder into a masked field)
- "pending": true scenes and an empty hosted link only warn
- writes demo-video/VIDEO_SCRIPT.md. Exit code 1 on any error.

Usage: python demo-video/check_scenes.py [--base-url http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from schema import missing_targets, validate  # noqa: E402
from videolib import ROOT, load_scenes, timeline, total_seconds, video_script_md  # noqa: E402

PAGES = ("/", "/?demo=1", "/shop", "/shop/penwright", "/shop/penwright/terms")
LEAK_FILES = ("demo-video/scenes.json", "demo-video/VIDEO_SCRIPT.md", "demo-video/out/words.json",
              "demo-video/out/captions.srt")


def password_leaks(password: str, root: Path = ROOT) -> list[str]:
    """The video files that contain the real password (never allowed)."""
    return [f"the password appears in {name}" for name in LEAK_FILES
            if (root / name).exists() and password in (root / name).read_text(encoding="utf-8")]


def ui_source(base_url: str | None, password: str) -> str:
    files = [*(ROOT / "app" / "templates").glob("*.html"), *(ROOT / "app" / "static").glob("*.js"),
             *(ROOT / "shop" / "templates").glob("*.html"), *(ROOT / "shop" / "static").glob("*.js")]
    parts = [f.read_text(encoding="utf-8") for f in files]
    if base_url:
        from signin import http_client, session_cookie
        with http_client(base_url, session_cookie(base_url, password), timeout=15) as http:
            parts += [http.get(page).text for page in PAGES]
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

    password = secrets.token_urlsafe(16)  # a throwaway app: any password works, signed in below (Phase 7)
    settings = Settings(_env_file=None, app_mode="mock", data_dir=data, demo_seed=False,  # type: ignore[call-arg]
                        demo_password=password)
    with TestClient(create_app(settings)) as client:
        email = next(u.email for u in client.app.state.store.load("users").items if u.id == "priya")  # type: ignore[attr-defined]
        client.post("/login", data={"email": email, "password": password, "next": "/"}).raise_for_status()
        return [client.get(page).text for page in PAGES]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="check the running app's pages")
    args = ap.parse_args()
    from signin import demo_password
    password = demo_password()  # exits with a clear message when DEMO_PASSWORD isn't set
    d = load_scenes()
    errors, warnings = validate(d)
    for m in missing_targets(d, ui_source(args.base_url, password)):
        (warnings if m.endswith("(pending scene)") else errors).append(m)
    out = ROOT / "demo-video" / "VIDEO_SCRIPT.md"
    out.write_text(video_script_md(d), encoding="utf-8")
    errors += password_leaks(password)
    mock = sum(s.duration for s in timeline(d, "mock"))
    sandbox = sum(s.duration for s in timeline(d, "sandbox"))
    print(f"{len(d['scenes'])} scenes, {total_seconds(d)} s (mock {mock:.0f} s without the PayPal proof scene, "
          f"sandbox {sandbox:.0f} s; cap {d['max_total_seconds']} s). Wrote {out.relative_to(ROOT)}.")
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR   {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

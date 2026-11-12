"""UI redesign v5 screenshots (docs/UI_REDESIGN.md): the redesigned pages at 1440x900 and 390x844, dark and light.

Starts its own mock server on throwaway data (ui_check.start_server), signs in as Priya, starts her Penwright trial
through the same API calls as demo-video/record_demo.py, moves to the check-in day, and saves full-page PNGs to
<out>/<step>/<theme>-<width>/<page>.png.

Usage: python scripts/shots_v5.py --step 1-tokens [--out docs/img/v5] [--day 5] [--pages intro,login,app,...]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_check  # noqa: E402  (server starter + console watcher)
from signin import add_session, demo_password, http_client, session_cookie  # noqa: E402

VIEWPORTS = ((1440, 900), (390, 844))
THEMES = ("dark", "light")
PAGES = {  # name -> (path, signed in)
    "intro": ("/", False), "login": ("/login", False), "app": ("/", True),
    "app-subs": ("/#subscriptions", True), "app-activity": ("/#activity", True), "presenter": ("/?demo=1", True),
}


def start_trial(base: str, cookie: str, day: int) -> None:
    """Priya subscribes to Penwright (mock approval), then the clock moves to `day`."""
    with http_client(base, cookie, timeout=60) as http:
        http.post("/api/demo/reset").raise_for_status()
        r = http.post("/api/review/preflight", json={"merchant_url": f"{base}/shop/penwright",
                                                     "plan_key": "penwright-pro", "user_id": "priya"})
        r.raise_for_status()
        review = r.json()["review_id"]
        r = http.post("/api/checkout/create", json={"merchant_id": "penwright", "plan_key": "penwright-pro",
                                                    "user_id": "priya"})
        r.raise_for_status()
        pid = r.json()["paypal_id"]
        http.post("/api/checkout/mock-approve", json={"paypal_id": pid}).raise_for_status()
        http.post("/api/subscriptions/register", json={"paypal_id": pid, "merchant_id": "penwright",
                                                       "plan_key": "penwright-pro", "user_id": "priya",
                                                       "review_id": review}).raise_for_status()
        if day:
            http.post("/api/demo/advance", params={"to_day": day}).raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True, help="folder name, e.g. 1-tokens")
    ap.add_argument("--out", default="docs/img/v5")
    ap.add_argument("--day", type=int, default=5)
    ap.add_argument("--pages", default=",".join(PAGES))
    args = ap.parse_args()
    password = demo_password()
    proc, base, data = ui_check.start_server(password)
    out = Path(args.out) / args.step
    shutil.rmtree(out, ignore_errors=True)
    try:
        cookie = session_cookie(base, password)
        start_trial(base, cookie, args.day)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for theme in THEMES:
                for w, h in VIEWPORTS:
                    folder = out / f"{theme}-{w}"
                    folder.mkdir(parents=True, exist_ok=True)
                    for name in args.pages.split(","):
                        path, signed_in = PAGES[name]
                        ctx = browser.new_context(viewport={"width": w, "height": h})
                        ctx.add_init_script(f"try {{ localStorage.setItem('sg-theme', '{theme}'); }} catch (e) {{}}")
                        if signed_in:
                            add_session(ctx, base, cookie)
                        page = ui_check.watch(ctx.new_page())
                        page.goto(base + path, wait_until="networkidle")
                        page.wait_for_timeout(900)  # count-ups and entrance motion settle
                        page.screenshot(path=str(folder / f"{name}.png"), full_page=True)
                        ctx.close()
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(data, ignore_errors=True)
    if ui_check.errors:
        print("console/page errors:", *ui_check.errors, sep="\n  ")
        return 1
    print(f"saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Record the demo's screen scenes (`python scripts/tasks.py demo-video-record`): Playwright, 1920x1080, one take.

- Asks the running app for its mode (/healthz) and resets the demo (/api/demo/reset) first.
- Runs every screen scene of scenes.json in order, then the "separate": true scenes (each after its off-screen
  "setup"). Each scene runs its actions, then waits out the rest of its duration. A scene is never extended: when
  its actions run over, the overrun is reported and the build trims the scene to its duration.
- `highlight` puts a teal outline on the target for about 2.5 s. `{on:N}` / `{sub:<plan>}` are resolved here.
- APP_MODE=sandbox (the video then shows "PayPal Sandbox", not "Demo data"): PayPal's approval window is the
  hand-recorded clip, so the recorder skips "mock_only" actions and registers the subscriptions that
  `make seed ARGS=--demo-subs` pre-approved (data/runtime/sandbox_ids.json). Run that seed again before each take.
- Writes demo-video/out/screen.webm + out/timing.json ({"scenes": [{"id", "start", "end"}]}, seconds into the
  recording). It continues past failed actions, lists every problem at the end, and exits 1 if there were any.

Usage: python demo-video/record_demo.py [--base-url URL] [--headed] [--sandbox-ids PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Error as PWError
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import ROOT, SUB_RE, is_clip, load_scenes  # noqa: E402

OUT = ROOT / "demo-video" / "out"
HIGHLIGHT_S = 2.5
USER = "priya"
HIGHLIGHT_JS = """(el, ms) => {
  el.scrollIntoView({block: "center", behavior: "smooth"});
  const old = [el.style.outline, el.style.outlineOffset, el.style.transition];
  el.style.transition = "outline-color .2s"; el.style.outline = "4px solid #14b8a6"; el.style.outlineOffset = "4px";
  setTimeout(() => { [el.style.outline, el.style.outlineOffset, el.style.transition] = old; }, ms);
}"""


class Recorder:
    def __init__(self, base: str, mode: str, sandbox_ids: dict[str, str]) -> None:
        self.base, self.mode, self.sandbox_ids = base.rstrip("/"), mode, sandbox_ids
        self.http = httpx.Client(base_url=self.base, timeout=120)
        self.subs: dict[str, str] = {}  # plan key -> local subscription id
        self.problems: list[str] = []
        self.timing: list[dict[str, Any]] = []
        self.t0 = 0.0

    def now(self) -> float:
        return time.monotonic() - self.t0

    # --- off-screen steps (setup, sandbox registration) -----------------------------------------------------
    def subscribe(self, plan_key: str, review_id: str | None = None) -> None:
        """A subscription without PayPal's window on screen: mock approves in place; sandbox registers the
        subscription `make seed ARGS=--demo-subs` pre-approved. Runs the companion's review first if none is given."""
        merchant = plan_key.split("-")[0]  # plan keys are <merchant>-<plan> (penwright-pro, quillnote-plus)
        if review_id is None:
            r = self.http.post("/api/review/preflight", json={"merchant_url": f"{self.base}/shop/{merchant}",
                                                              "plan_key": plan_key, "user_id": USER})
            r.raise_for_status()
            review_id = r.json()["review_id"]
        if self.mode == "sandbox":
            paypal_id = self.sandbox_ids[plan_key]
        else:
            r = self.http.post("/api/checkout/create", json={"merchant_id": merchant, "plan_key": plan_key,
                                                            "user_id": USER})
            r.raise_for_status()
            paypal_id = r.json()["paypal_id"]
            self.http.post("/api/checkout/mock-approve", json={"paypal_id": paypal_id}).raise_for_status()
        r = self.http.post("/api/subscriptions/register", json={"paypal_id": paypal_id, "merchant_id": merchant,
                                                                "plan_key": plan_key, "user_id": USER,
                                                                "review_id": review_id})
        if r.status_code == 202:
            raise RuntimeError(f"{plan_key}: PayPal status is {r.json().get('status')}, not ACTIVE. Run "
                               "`make seed ARGS=--demo-subs` again for a fresh pre-approved subscription.")
        r.raise_for_status()
        self.subs[plan_key] = r.json()["id"]

    def latest_review(self, merchant: str) -> str | None:
        reviews = [r for r in self.http.get("/api/reviews", params={"merchant": merchant}).json()
                   if r.get("subscription_id") is None]
        return reviews[-1]["id"] if reviews else None

    # --- on-screen actions ----------------------------------------------------------------------------------
    def act(self, page: Page, a: dict[str, Any], budget: float) -> None:
        kind, target = a["action"], a.get("target")
        loc = page.get_by_test_id(target).first if target else None
        # an explicit "timeout" (a slow AI review in sandbox) wins; otherwise wait at most the scene's time left
        ms = int(1000 * (float(a["timeout"]) if "timeout" in a else min(10.0, max(budget, 1.0))))
        if kind == "goto":
            url = SUB_RE.sub(lambda m: self.subs[m.group(1)], a["url"])
            page.goto(self.base + url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PWError:
                pass
        elif kind == "click":
            loc.click(timeout=ms)  # type: ignore[union-attr]
        elif kind == "hover":
            loc.hover(timeout=ms)  # type: ignore[union-attr]
        elif kind == "type":
            loc.fill("", timeout=ms)  # type: ignore[union-attr]
            loc.press_sequentially(a["text"], delay=90)  # type: ignore[union-attr]
        elif kind == "press":
            page.keyboard.press(a["key"])
        elif kind == "wait_for":
            loc.wait_for(state="visible", timeout=ms)  # type: ignore[union-attr]
        elif kind == "wait":
            page.wait_for_timeout(1000 * float(a["seconds"]))
        elif kind == "scroll_to":
            loc.scroll_into_view_if_needed(timeout=ms)  # type: ignore[union-attr]
        elif kind == "highlight":
            loc.wait_for(state="visible", timeout=ms)  # type: ignore[union-attr]
            loc.evaluate(HIGHLIGHT_JS, int(HIGHLIGHT_S * 1000))  # type: ignore[union-attr]
            page.wait_for_timeout(HIGHLIGHT_S * 1000)
        page.wait_for_timeout(250)  # a beat between steps so the viewer can follow

    def scene(self, page: Page, s: dict[str, Any]) -> None:
        sid, duration = s["id"], float(s["duration"])
        if s.get("setup", {}).get("subscribe"):
            try:
                self.subscribe(s["setup"]["subscribe"])
            except (httpx.HTTPError, RuntimeError, KeyError) as e:
                self.problems.append(f"{sid}: setup failed: {e}")
                return
        start = self.now()
        for a in s["actions"]:
            if a.get("mock_only") and self.mode == "sandbox":
                continue
            left = start + duration - self.now()
            if left <= 0:
                self.problems.append(f"{sid}: out of time before {a['action']} {a.get('target', '')}; the build "
                                     "trims the scene (shorten its actions)")
                break
            try:
                self.act(page, a, left)
            except (PWError, KeyError) as e:
                self.problems.append(f"{sid}: {a['action']} {a.get('target') or a.get('url', '')}: "
                                     f"{str(e).splitlines()[0][:160]}")
        left = start + duration - self.now()
        if left > 0:
            page.wait_for_timeout(left * 1000)
        else:
            self.problems.append(f"{sid}: ran {-left:.1f} s over its {duration:.0f} s; the build trims it")
        self.timing.append({"id": sid, "start": round(start, 3), "end": round(self.now(), 3)})
        print(f"  {sid:<20} {start:6.1f}s -> {self.now():6.1f}s")
        if s.get("sandbox_subscribe") and self.mode == "sandbox":  # off screen, after the scene
            plan_key = s["sandbox_subscribe"]
            try:
                self.subscribe(plan_key, self.latest_review(plan_key.split("-")[0]))
            except (httpx.HTTPError, RuntimeError, KeyError) as e:
                self.problems.append(f"{sid}: registering the pre-approved {plan_key} failed: {e}")

    def run(self, d: dict[str, Any], headed: bool) -> None:
        self.http.post("/api/demo/reset").raise_for_status()
        vp = d["viewport"]
        raw = OUT / "raw"
        shutil.rmtree(raw, ignore_errors=True)
        main = [s for s in d["scenes"] if not is_clip(s) and not s.get("separate")]
        later = [s for s in d["scenes"] if not is_clip(s) and s.get("separate")]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            ctx = browser.new_context(viewport=vp, record_video_dir=str(raw), record_video_size=vp,
                                      color_scheme="light")
            page = ctx.new_page()
            self.t0 = time.monotonic()  # the video starts with the page
            for s in [*main, *later]:
                self.scene(page, s)
            video = page.video
            ctx.close()  # writes the video
            browser.close()
            if video is None:
                raise RuntimeError("Playwright didn't record a video")
            shutil.move(video.path(), OUT / "screen.webm")
        (OUT / "timing.json").write_text(json.dumps({"scenes": self.timing}, indent=2), encoding="utf-8")
        shutil.rmtree(raw, ignore_errors=True)


def sandbox_ids(path: Path, d: dict[str, Any]) -> dict[str, str]:
    needed = {s["sandbox_subscribe"] for s in d["scenes"] if s.get("sandbox_subscribe")}
    needed |= {s["setup"]["subscribe"] for s in d["scenes"] if s.get("setup", {}).get("subscribe")}
    ids = json.loads(path.read_text(encoding="utf-8")).get("demo_subscriptions", {}) if path.exists() else {}
    missing = sorted(needed - set(ids))
    if missing:
        raise SystemExit(f"Sandbox recording needs pre-approved subscriptions for {', '.join(missing)} in {path}. "
                         "Run `make seed ARGS=--demo-subs` (python scripts/tasks.py seed --demo-subs) first.")
    return ids


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d = load_scenes()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=d.get("base_url", "http://127.0.0.1:8000"))
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--sandbox-ids", type=Path,
                    default=Path(os.environ.get("DATA_DIR", ROOT / "data")) / "runtime" / "sandbox_ids.json")
    args = ap.parse_args()
    try:
        health = httpx.get(args.base_url.rstrip("/") + "/healthz", timeout=15).json()
    except httpx.HTTPError:
        print(f"The app isn't running at {args.base_url}. Start it first: `make dev` (mock) or `make dev-sandbox`.")
        return 1
    mode = health.get("mode", "mock")
    ids = sandbox_ids(args.sandbox_ids, d) if mode == "sandbox" else {}
    OUT.mkdir(parents=True, exist_ok=True)
    rec = Recorder(args.base_url, mode, ids)
    print(f"recording in {mode} mode from {args.base_url}")
    rec.run(d, args.headed)
    print(f"wrote {(OUT / 'screen.webm').relative_to(ROOT)} and {(OUT / 'timing.json').relative_to(ROOT)}")
    if mode == "sandbox":
        print("Afterwards: cancel any sandbox subscription still ACTIVE (Quillnote is a Layer 2 merchant, so use the "
              "buyer's PayPal Automatic payments page).")
    for p in rec.problems:
        print(f"PROBLEM {p}")
    return 1 if rec.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

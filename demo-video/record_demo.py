"""Record the app scenes (`python scripts/tasks.py demo-video-record`): Playwright, one take, at scenes.json's
app_viewport (1600x900: it is scaled to the stage's 1280x720 hole, so text stays sharp).

- Reads the app's mode from /healthz (written to timing.json: the stage's pill comes from it) and resets the demo.
- Walks the scenes in order. app scenes run their actions; card/slide scenes hold their time (the stage draws them),
  so the recording follows the video. paypal scenes run only in sandbox mode (real PayPal sandbox pages, logged in
  as the sandbox buyer OFF camera before the take); in mock mode they're skipped and the stage gives their time to
  the scene's mock_fallback. A scene is never extended: an overrun is reported and the build trims it.
- "setup" runs off screen before the scene: reset (a fresh demo), day: N (the sim clock), subscribe: <plan>.
  "sandbox_subscribe" registers the pre-approved sandbox subscription after the scene (`make seed ARGS=--demo-subs`).
- highlight = a thick yellow glow on the target for about 2.5 s. `{on:N}`, `{sub:<plan>}`, `{paypal_autopay}` resolved.
- Writes out/screen.webm + out/timing.json ({"mode", "base_url", "viewport", "scenes": [{"id", "start", "end"}],
  "urls": [{"t", "url"}]}: every page the recorder really visited, for the frame's URL bar). It continues past
  failed actions, lists every problem at the end, and exits 1 if any (problems in a "pending" scene only warn).
Usage: python demo-video/record_demo.py [--base-url URL] [--headed] [--sandbox-ids PATH]
"""

from __future__ import annotations

import argparse
import asyncio
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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from signin import add_session, demo_password, http_client, session_cookie  # noqa: E402
from videolib import OUT, ROOT, SUB_RE, load_scenes, timeline  # noqa: E402

HIGHLIGHT_S = 2.5
USER = "priya"
HIGHLIGHT_JS = """(el, ms) => {
  el.scrollIntoView({block: "center", behavior: "smooth"});
  const keep = ["outline", "outlineOffset", "boxShadow", "borderRadius", "transition"].map((k) => [k, el.style[k]]);
  el.style.transition = "box-shadow .25s, outline-color .25s";
  el.style.outline = "4px solid #f5b942"; el.style.outlineOffset = "4px";
  el.style.boxShadow = "0 0 0 10px rgba(245,185,66,.28), 0 0 34px 12px rgba(245,185,66,.55)";
  if (!el.style.borderRadius) el.style.borderRadius = "8px";
  setTimeout(() => keep.forEach(([k, v]) => { el.style[k] = v; }), ms);
}"""


class Recorder:
    def __init__(self, base: str, mode: str, sandbox_ids: dict[str, str], autopay: str, session: str) -> None:
        self.base, self.mode, self.sandbox_ids, self.autopay = base.rstrip("/"), mode, sandbox_ids, autopay
        self.session = session  # Priya's sg_session cookie (Phase 7): the httpx client and the browser both use it
        self.http = http_client(self.base, session, timeout=120)
        self.subs: dict[str, str] = {}  # plan key -> local subscription id
        self.problems: list[str] = []
        self.notes: list[str] = []  # problems in pending scenes: reported, not failing
        self.timing: list[dict[str, Any]] = []
        self.urls: list[dict[str, Any]] = []
        self.t0 = 0.0

    def now(self) -> float:
        return time.monotonic() - self.t0

    # --- off-screen steps -------------------------------------------------------------------------------------
    def subscribe(self, plan_key: str, review_id: str | None = None) -> None:
        """A subscription without PayPal's window on screen: mock approves in place; sandbox registers the
        subscription `make seed ARGS=--demo-subs` pre-approved. Runs the companion's review first if none given."""
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

    def setup(self, setup: dict[str, Any]) -> None:
        if setup.get("reset"):
            self.http.post("/api/demo/reset").raise_for_status()
            self.subs.clear()
        if "day" in setup:
            self.http.post("/api/demo/advance", params={"to_day": setup["day"]}).raise_for_status()
        if setup.get("subscribe"):
            self.subscribe(setup["subscribe"])

    def latest_review(self, merchant: str) -> str | None:
        reviews = [r for r in self.http.get("/api/reviews", params={"merchant": merchant}).json()
                   if r.get("subscription_id") is None]
        return reviews[-1]["id"] if reviews else None

    # --- on-screen actions ----------------------------------------------------------------------------------
    def act(self, page: Page, a: dict[str, Any], budget: float) -> None:
        kind, target = a["action"], a.get("target")
        loc = page.get_by_test_id(target).first if target else None
        ms = int(1000 * (float(a["timeout"]) if "timeout" in a else min(10.0, max(budget, 1.0))))
        if kind == "goto":
            url = SUB_RE.sub(lambda m: self.subs[m.group(1)], a["url"]).replace("{paypal_autopay}", self.autopay)
            page.goto(url if url.startswith("http") else self.base + url, wait_until="domcontentloaded", timeout=60000)
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

    def scene(self, page: Page, s: dict[str, Any], slots: dict[str, float]) -> None:
        sid = s["id"]
        report = self.notes if s.get("pending") else self.problems
        if sid not in slots:  # a paypal scene outside sandbox mode
            print(f"  {sid:<18} skipped (mock mode: its {s['duration']} s go to {s['mock_fallback']})")
            return
        duration = slots[sid]  # the scene's time on this mode's timeline (a mock_fallback scene holds longer)
        if s.get("setup"):
            try:
                self.setup(s["setup"])
            except (httpx.HTTPError, RuntimeError, KeyError) as e:
                report.append(f"{sid}: setup failed: {e}")
        start = self.now()
        for a in s.get("actions", []):
            if a.get("mock_only") and self.mode == "sandbox":
                continue
            left = start + duration - self.now()
            if left <= 0:
                report.append(f"{sid}: out of time before {a['action']} {a.get('target', '')}; the build trims "
                              "the scene (shorten its actions)")
                break
            try:
                self.act(page, a, left)
            except (PWError, KeyError) as e:
                report.append(f"{sid}: {a['action']} {a.get('target') or a.get('url', '')}: "
                              f"{str(e).splitlines()[0][:160]}")
        left = start + duration - self.now()
        if left > 0:
            page.wait_for_timeout(left * 1000)
        else:
            report.append(f"{sid}: ran {-left:.1f} s over its {duration:.0f} s; the build trims it")
        self.timing.append({"id": sid, "start": round(start, 3), "end": round(self.now(), 3)})
        print(f"  {sid:<18} {start:6.1f}s -> {self.now():6.1f}s  {s['kind']}")
        if s.get("sandbox_subscribe") and self.mode == "sandbox":  # off screen, after the scene
            plan_key = s["sandbox_subscribe"]
            try:
                self.subscribe(plan_key, self.latest_review(plan_key.split("-")[0]))
            except (httpx.HTTPError, RuntimeError, KeyError) as e:
                self.problems.append(f"{sid}: registering the pre-approved {plan_key} failed: {e}")

    def run(self, d: dict[str, Any], headed: bool, state: Path | None) -> None:
        self.http.post("/api/demo/reset").raise_for_status()
        vp = d["app_viewport"]
        raw = OUT / "raw"
        shutil.rmtree(raw, ignore_errors=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            ctx = browser.new_context(viewport=vp, record_video_dir=str(raw), record_video_size=vp,
                                      color_scheme="light", storage_state=str(state) if state else None)
            add_session(ctx, self.base, self.session)
            page = ctx.new_page()
            self.t0 = time.monotonic()  # the video starts with the page
            page.on("framenavigated", lambda f: f == page.main_frame and self.urls.append(
                {"t": round(self.now(), 3), "url": f.url}))
            slots = {x.id: x.duration for x in timeline(d, self.mode)}
            for s in d["scenes"]:
                self.scene(page, s, slots)
            video = page.video
            ctx.close()  # writes the video
            browser.close()
            if video is None:
                raise RuntimeError("Playwright didn't record a video")
            shutil.move(video.path(), OUT / "screen.webm")
        (OUT / "timing.json").write_text(json.dumps({
            "mode": self.mode, "base_url": self.base, "viewport": vp, "scenes": self.timing,
            "urls": [u for u in self.urls if u["url"] != "about:blank"]}, indent=2), encoding="utf-8")
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


def buyer_login(path: Path, email: str, password: str) -> None:
    """Log in to PayPal sandbox as the buyer in a separate, unrecorded browser and save the cookies, so the
    paypal scene opens already signed in: no email or password is ever typed on camera."""
    from playwright.async_api import async_playwright

    from app.integrations.sandbox_buyer import _login

    async def go() -> None:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.goto("https://www.sandbox.paypal.com/signin", wait_until="domcontentloaded")
            await _login(page, email, password)
            await page.wait_for_load_state("networkidle", timeout=30000)
            await ctx.storage_state(path=str(path))
            await browser.close()
    asyncio.run(go())


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
    session = session_cookie(args.base_url, demo_password())  # clear message if DEMO_PASSWORD is missing
    OUT.mkdir(parents=True, exist_ok=True)
    ids, state, autopay = {}, None, ""
    if mode == "sandbox":
        sys.path.insert(0, str(ROOT))
        from app.config import load_settings
        settings = load_settings()
        ids, autopay = sandbox_ids(args.sandbox_ids, d), settings.paypal_autopay_url
        if any(s["kind"] == "paypal" for s in d["scenes"]):
            state = OUT / "paypal_state.json"  # gitignored (out/); deleted after the take
            buyer_login(state, settings.paypal_sandbox_buyer_email, settings.paypal_sandbox_buyer_password)
    rec = Recorder(args.base_url, mode, ids, autopay, session)
    print(f"recording in {mode} mode from {args.base_url} at {d['app_viewport']['width']}x"
          f"{d['app_viewport']['height']}")
    try:
        rec.run(d, args.headed, state)
    finally:
        if state:
            state.unlink(missing_ok=True)
    print(f"wrote {(OUT / 'screen.webm').relative_to(ROOT)} and {(OUT / 'timing.json').relative_to(ROOT)}")
    if mode == "sandbox":
        print("Afterwards: cancel any sandbox subscription still ACTIVE (Quillnote is a Layer 2 merchant, so use the "
              "buyer's PayPal Automatic payments page).")
    for n in rec.notes:
        print(f"PENDING {n}")
    for p in rec.problems:
        print(f"PROBLEM {p}")
    return 1 if rec.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

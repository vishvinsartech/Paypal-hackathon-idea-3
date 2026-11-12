"""Screenshots of every demo screen at desktop and phone size (FIX_PLAN Phase 0; Phase 3 screens).

Starts a mock server on throwaway data (reusing ui_check.start_server), walks the demo once per viewport and saves
PNGs to <out>/<phase>/<viewport>/NN_<name>.png. Steps are forgiving: if a selector is missing (the UI changes
between phases) the step is reported and skipped instead of failing, so the script can be re-run after each phase.

Usage: python scripts/shots.py [--phase p0] [--out docs/img/v3] [--headed] [--base-url URL]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
from playwright.sync_api import Error as PWError
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_check  # noqa: E402  (reuse the server starter and console watcher)

VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
SECTIONS = ("overview", "activity", "emails")
skipped: list[str] = []


class Shooter:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.n = 0

    def __call__(self, page: Page, name: str, full: bool = False) -> None:
        self.n += 1
        page.wait_for_timeout(700)  # entrance animations settle
        try:  # U29: the count-up has finished (pages without it never set data-ready; that's fine)
            page.wait_for_selector("html[data-ready='1']", state="attached", timeout=3000)
        except PWError:
            pass
        page.screenshot(path=str(self.folder / f"{self.n:02d}_{name}.png"), full_page=full)


def attempt(label: str, fn: Callable[[], object]) -> bool:
    try:
        fn()
        return True
    except (PWError, AssertionError, StopIteration, httpx.HTTPError) as e:
        skipped.append(f"{label}: {str(e).splitlines()[0][:140]}")
        return False


def nav(page: Page, url: str) -> None:
    """Open a page without hanging on a slow CDN: DOM ready, then up to 10 s for the network to go quiet."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWError:
        skipped.append(f"{url}: network not idle after 10 s (CDN?)")


def click(page: Page, testid: str, timeout: int = 4000) -> None:
    page.get_by_test_id(testid).first.click(timeout=timeout)


def advance(base: str, day: int) -> None:
    httpx.post(f"{base}/api/demo/advance", params={"days": 0, "to_day": day}, timeout=60).raise_for_status()


def user_id(base: str) -> str:
    page = httpx.get(f"{base}/", timeout=10).text
    marker = 'data-user="'
    i = page.find(marker)
    return page[i + len(marker):page.find('"', i + len(marker))] if i >= 0 else "priya"


def walk(base: str, folder: Path, size: tuple[int, int], headed: bool) -> None:
    """Phase 3: one product view at `/` (presenter bar via ?demo=1), the shop, the companion, the evidence tabs."""
    httpx.post(f"{base}/api/demo/reset", timeout=60).raise_for_status()
    shoot = Shooter(folder)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
        page = ui_check.watch(ctx.new_page())

        nav(page, f"{base}/")
        shoot(page, "home_day0_empty")
        nav(page, f"{base}/shop")
        shoot(page, "shop_index", full=True)
        nav(page, f"{base}/shop/penwright")
        shoot(page, "shop_penwright", full=True)
        attempt("shop terms", lambda: click(page, "shop-terms-toggle"))
        if attempt("companion open", lambda: (click(page, "shop-paypal-btn"),
                                              page.get_by_test_id("companion-risk").wait_for(timeout=20000))):
            shoot(page, "companion")  # viewport only: shows what is visible when it opens (B1)
            attempt("companion evidence", lambda: page.get_by_test_id("companion-evidence").locator("summary").click(
                timeout=1500))
            shoot(page, "companion_evidence")
            attempt("companion continue", lambda: (click(page, "companion-continue"),
                                                   page.get_by_test_id("shop-open-subguard").wait_for(timeout=15000)))
            shoot(page, "shop_subscribed", full=True)

        nav(page, f"{base}/?demo=1")
        shoot(page, "home_day0_presenter")
        nav(page, f"{base}/")
        shoot(page, "home_day0", full=True)
        attempt("paypal footer", lambda: page.get_by_test_id("paypal-verified").first.locator("summary").click())
        attempt("paypal footer shot", lambda: (page.get_by_test_id("paypal-status").first.wait_for(timeout=5000),
                                               shoot(page, "home_day0_paypal_footer")))

        advance(base, 5)
        nav(page, f"{base}/")
        shoot(page, "home_day5_checkin", full=True)
        attempt("chat", lambda: (click(page, "chat-open"), shoot(page, "chat_open"),
                                 page.locator("#chat-close").click(timeout=2000)))
        if attempt("cancel", lambda: (click(page, "alert-cancel"),
                                      page.get_by_test_id("confirm-card").first.wait_for(timeout=5000))):
            shoot(page, "cancel_confirm")
            if attempt("confirm", lambda: (click(page, "confirm-button"),
                                           page.get_by_test_id("email-preview").wait_for(timeout=10000))):
                shoot(page, "email_modal")
                attempt("email close", lambda: click(page, "email-dismiss"))
        shoot(page, "home_day5_cancelled", full=True)

        advance(base, 11)
        nav(page, f"{base}/?demo=1")
        shoot(page, "home_day11_presenter")
        attempt("audit drawer", lambda: (click(page, "audit-full-toggle", 2000),
                                         page.get_by_test_id("audit-log-grid").locator(".ag-row").first.wait_for(),
                                         shoot(page, "audit_drawer"), page.keyboard.press("Escape")))
        nav(page, f"{base}/")
        shoot(page, "home_day11", full=True)
        for sec in SECTIONS:
            tab = page.get_by_test_id(f"nav-{sec}")
            if tab.count() and attempt(f"section {sec}", lambda tab=tab: tab.first.click(timeout=2000)):
                shoot(page, f"home_section_{sec}", full=True)

        uid = user_id(base)
        subs = httpx.get(f"{base}/api/subscriptions", params={"user": uid}, timeout=10).json()
        if subs:
            nav(page, f"{base}/subscriptions/{subs[0]['id']}?user={uid}")
            shoot(page, "evidence_summary", full=True)
            for tab in ("evidence", "paypal", "activity"):
                if attempt(f"evidence tab {tab}", lambda tab=tab: click(page, f"ev-tab-{tab}")):
                    page.wait_for_timeout(600)
                    shoot(page, f"evidence_{tab}", full=True)
        quillnote(base, page, shoot, uid)
        browser.close()


def quillnote(base: str, page: object, shoot: Shooter, uid: str) -> None:
    """v3 Phase 2: Quillnote checkout + companion, the AI vs basic panel, and the Layer 2 ACTION NEEDED card."""
    nav(page, f"{base}/shop/quillnote")  # type: ignore[arg-type]
    shoot(page, "shop_quillnote", full=True)
    if not attempt("quillnote companion", lambda: (click(page, "shop-paypal-btn"),  # type: ignore[arg-type]
                                                   page.get_by_test_id("companion-risk").wait_for(timeout=20000))):  # type: ignore[attr-defined]
        return
    shoot(page, "quillnote_companion")
    attempt("quillnote continue", lambda: (click(page, "companion-continue"),  # type: ignore[arg-type]
                                           page.get_by_test_id("shop-open-subguard").wait_for(timeout=15000)))  # type: ignore[attr-defined]
    sub = next((s for s in httpx.get(f"{base}/api/subscriptions", params={"user": uid}, timeout=10).json()
                if s["plan_key"] == "quillnote-plus"), None)
    if sub is None:
        return
    nav(page, f"{base}/subscriptions/{sub['id']}?user={uid}")  # type: ignore[arg-type]
    shoot(page, "quillnote_ai_vs_basic", full=True)
    nav(page, f"{base}/")  # type: ignore[arg-type]
    card = page.get_by_test_id("sub-card").filter(has=page.get_by_test_id("status-quillnote"))  # type: ignore[attr-defined]
    if attempt("quillnote cancel", lambda: (card.get_by_test_id("sub-cancel").click(timeout=3000),
                                            click(page, "confirm-button"),  # type: ignore[arg-type]
                                            page.get_by_test_id("email-preview").wait_for(timeout=10000))):  # type: ignore[attr-defined]
        shoot(page, "quillnote_email")
        attempt("quillnote email close", lambda: click(page, "email-dismiss"))  # type: ignore[arg-type]
        attempt("action needed", lambda: page.get_by_test_id("action-needed").wait_for(timeout=10000))  # type: ignore[attr-defined]
        shoot(page, "quillnote_action_needed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="p0")
    ap.add_argument("--out", default=str(ui_check.ROOT / "docs" / "img" / "v3"))
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--base-url")
    args = ap.parse_args()
    proc = data = None
    base = args.base_url
    if not base:
        proc, base, data = ui_check.start_server()
    try:
        for name, size in VIEWPORTS.items():
            folder = Path(args.out) / args.phase / name
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
            walk(base, folder, size, args.headed)
            print(f"{name}: {len(list(folder.glob('*.png')))} screenshots in {folder}")
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(10)
        if data is not None:
            shutil.rmtree(data, ignore_errors=True)
    for s in skipped:
        print(f"  skipped: {s}")
    for e in ui_check.errors:
        print(f"  console: {e}")
    return 1 if ui_check.errors else 0


if __name__ == "__main__":
    sys.exit(main())

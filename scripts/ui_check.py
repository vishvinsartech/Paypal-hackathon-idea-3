"""Milestone 6 browser check: the full Story A in mock mode, driven through the real UI with Playwright.

Starts its own mock server on a free port with a throwaway DATA_DIR (unless --base-url is given), then:
shop -> companion (risk ~87, Continue) -> add-on removed (confirm card) -> timer chip -> Day 5 toast ->
Day 6 auto-cancel + notice -> Day 15 blocked charge -> Day 21 price rise -> chat "$228/yr" card -> confirm ->
KPI $872.76 -> audit-log CSV export -> subscription page. Fails on any console error or page error.

Usage: python scripts/ui_check.py [--base-url http://127.0.0.1:8000] [--headed] [--shots DIR]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []
SHOTS: Path | None = None


def shot(page: Page, name: str) -> None:
    if SHOTS is not None:
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def watch(page: Page) -> Page:
    def on_console(m: object) -> None:
        if getattr(m, "type", "") == "error":
            errors.append(f"{page.url}: console.error: {getattr(m, 'text', '')}")

    page.on("console", on_console)
    page.on("pageerror", lambda e: errors.append(f"{page.url}: pageerror: {e}"))
    return page


def start_server() -> tuple[subprocess.Popen[bytes], str, Path]:
    data = Path(tempfile.mkdtemp(prefix="subguard-ui-"))
    shutil.copytree(ROOT / "data" / "seed", data / "seed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "APP_MODE": "mock", "DATA_DIR": str(data), "DEMO_SEED": "true"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port",
                             str(port), "--workers", "1"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                return proc, base, data
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("server didn't start")


def step(msg: str) -> None:
    print(f"  - {msg}", flush=True)


def story_a(base: str, headed: bool) -> None:
    httpx.post(f"{base}/api/demo/reset", timeout=30).raise_for_status()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        dash = watch(ctx.new_page())
        dash.goto(f"{base}/?demo=1")
        expect(dash.get_by_test_id("subs-grid").locator(".ag-row")).to_have_count(1)
        step("dashboard loaded with Framewise in the grid")

        with ctx.expect_page() as shop_info:
            dash.get_by_test_id("demo-open-shop").click()
        shop = watch(shop_info.value)
        shop.wait_for_load_state()
        shop.get_by_test_id("shop-terms-toggle").click()
        shop.get_by_test_id("shop-paypal-btn").click()
        risk = shop.get_by_test_id("companion-risk")
        expect(risk).to_be_visible(timeout=20000)
        score = int(re.search(r"(\d+)/100", risk.inner_text()).group(1))  # type: ignore[union-attr]
        assert abs(score - 87) <= 5, score
        for t in ("NOTICE_PERIOD", "TERMS_MISMATCH", "PROMPT_INJECTION_ATTEMPT"):
            expect(shop.get_by_test_id(f"finding-{t}").first).to_be_visible()
        shot(shop, "01_companion")
        shop.get_by_test_id("companion-continue").click()
        expect(shop.get_by_test_id("shop-open-subguard")).to_be_visible(timeout=15000)
        step(f"companion: risk {score}, findings shown, Continue -> subscribed (+ add-on)")

        dash.bring_to_front()
        dash.reload()
        dash.get_by_test_id("addon-remove-yes").click()
        card = dash.get_by_test_id("confirm-card")
        expect(card).to_contain_text("$119.88/yr")
        card.get_by_test_id("confirm-button").click()
        expect(dash.get_by_test_id("status-penwright-addon")).to_have_text("CANCELLED")
        expect(dash.get_by_test_id("timer-chip")).to_contain_text("Cancel on Day 6 unless you keep it")
        step("add-on removed via confirm card; timer chip shows Day 6")

        dash.get_by_test_id("sim-jump-5").click()
        expect(dash.get_by_test_id("toast-alert").filter(has_text="real deadline is in 2 days")).to_be_visible()
        step("Day 5: reminder toast")
        dash.get_by_test_id("sim-jump-6").click()
        expect(dash.get_by_test_id("status-penwright")).to_have_text("CANCELLED")
        expect(dash.get_by_test_id("cancellation-notice").first).to_contain_text("cancel@penwright.example")
        shot(dash, "02_day6")
        step("Day 6: auto-cancelled, cancellation notice stored")
        dash.get_by_test_id("sim-jump-15").click()
        expect(dash.get_by_test_id("blocked-charge").first).to_contain_text("First charge due today: blocked")
        step("Day 15: blocked charge")
        dash.get_by_test_id("sim-jump-21").click()
        expect(dash.get_by_test_id("demo-day")).to_have_text("21")
        dash.get_by_test_id("sim-price-rise").click()
        expect(dash.get_by_test_id("alert-price-rise")).to_contain_text("$19")
        expect(dash.get_by_test_id("alert-price-rise").get_by_test_id("alert-keep")).to_have_text("Keep at $19")
        step("Day 21: price-rise alert with Keep at $19 / Cancel")

        dash.get_by_test_id("chat-open").click()
        dash.get_by_test_id("chat-input").fill("Is it still worth it? I barely used it.")
        dash.get_by_test_id("chat-send").click()
        chat_card = dash.locator("#chat").get_by_test_id("confirm-card")
        expect(chat_card).to_contain_text("$228/yr")
        answer = "You opened it 3 times this month. Keeping it costs $228 a year."
        expect(dash.locator("#chat-log")).to_contain_text(answer)
        shot(dash, "03_chat_card")
        chat_card.get_by_test_id("confirm-button").click()
        expect(dash.get_by_test_id("chat-done")).to_contain_text("Framewise: cancelled in PayPal.")
        expect(dash.locator("#kpi-protected")).to_have_text("$872.76/yr")
        step("chat: $228/yr card -> confirmed -> done; Money protected $872.76/yr")

        expect(dash.get_by_test_id("audit-chain")).to_contain_text("chain verified")
        with dash.expect_download() as dl_info:
            dash.get_by_test_id("audit-log-export").click()
        csv_text = Path(dl_info.value.path()).read_text(encoding="utf-8")
        assert "paypal_cancel" in csv_text and "R2" in csv_text, "CSV export missing rows"
        step(f"audit log CSV exported ({len(csv_text.splitlines())} lines), chain verified")

        sub_id = next(s["id"] for s in httpx.get(f"{base}/api/subscriptions?user=priya").json()
                      if s["plan_key"] == "penwright-pro")
        page = watch(ctx.new_page())
        page.goto(f"{base}/subscriptions/{sub_id}?user=priya")
        expect(page.get_by_test_id("risk-score")).to_contain_text("/100")
        expect(page.get_by_test_id("finding-PROMPT_INJECTION_ATTEMPT").first).to_be_visible()
        expect(page.get_by_test_id("cancellation-notice")).to_contain_text("SHA-256")
        expect(page.locator("#sub-audit-grid .ag-row").first).to_be_visible()
        shot(page, "04_subscription")
        step("subscription page: findings grid, notice, audit entries")

        john = watch(ctx.new_page())
        john.goto(f"{base}/?user=john")
        expect(john.get_by_test_id("subs-grid").locator(".ag-row")).to_have_count(1)
        expect(john.get_by_test_id("status-lumen")).to_have_text("ACTIVE")
        step("John's dashboard: Lumen active")
        browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--shots", help="save full-page screenshots to this folder")
    args = ap.parse_args()
    global SHOTS
    if args.shots:
        SHOTS = Path(args.shots)
        SHOTS.mkdir(parents=True, exist_ok=True)
    proc = data = None
    base = args.base_url
    if not base:
        proc, base, data = start_server()
    print(f"UI check against {base}")
    try:
        story_a(base, args.headed)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(10)
        if data is not None:
            shutil.rmtree(data, ignore_errors=True)
    if errors:
        print("Console/page errors:\n  " + "\n  ".join(errors))
        return 1
    print("UI check passed: Story A in the browser, no console errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

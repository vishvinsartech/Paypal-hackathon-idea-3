"""Browser check: the demo story (Priya + Penwright) in mock mode, driven through the real UI with Playwright.

Starts its own mock server on a free port with a throwaway DATA_DIR (unless --base-url is given), then:
shop -> companion (risk ~87, summary, "I'll check with you...", Continue) -> timer shown -> Day 5 check-in toast ->
Priya's dashboard (card, Day 10 vs Day 7, usage + advice, chat) -> Cancel -> confirm card $524.88/yr -> email preview
(edit, empty To disables Send, Gmail link; no toasts) -> Day 11 blocked charge + proof banner -> charts, activity grid,
theme toggle -> audit-log CSV export -> subscription page.
Fails on any console error or page error.

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


def story(base: str, headed: bool) -> None:
    httpx.post(f"{base}/api/demo/reset", timeout=30).raise_for_status()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        dash = watch(ctx.new_page())
        dash.goto(f"{base}/?demo=1")
        expect(dash.get_by_test_id("timeline")).to_contain_text("No subscriptions yet.")
        expect(dash.get_by_test_id("user-switch")).to_have_count(0)
        step("dashboard loaded: Priya, no subscriptions yet, no user switcher")

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
        expect(shop.get_by_test_id("companion-summary")).to_be_visible()
        expect(shop.get_by_test_id("companion-promise")).to_have_text("I'll check with you before your trial runs out.")
        shot(shop, "01_companion")
        shop.get_by_test_id("companion-continue").click()
        expect(shop.get_by_test_id("shop-open-subguard")).to_be_visible(timeout=15000)
        step(f"Day 0: companion risk {score}, summary + promise shown, Continue -> subscribed")

        dash.bring_to_front()
        dash.reload()
        promise = "I'll check with you before your trial runs out."
        expect(dash.get_by_test_id("alert-timer-set")).to_contain_text(promise)
        expect(dash.get_by_test_id("timer-chip")).to_contain_text("Check-in Day 5")
        for gone in ("subs-grid", "chart-cost", "kpi-patterns", "kpi-cancelled", "kpi-watches"):
            expect(dash.get_by_test_id(gone)).to_have_count(0)
        expect(dash.get_by_test_id("layer2-controls")).to_be_hidden()
        expect(dash.locator(".topbar").get_by_test_id("health-dots")).to_have_count(0)
        dash.get_by_test_id("dev-menu").locator("summary").click()
        expect(dash.get_by_test_id("dev-docs")).to_be_visible()
        step("Live demo = control room: timer shown, Money protected only, dev links in the footer menu")

        me = watch(ctx.new_page())  # Priya's dashboard in its own window, like a presenter would
        me.goto(f"{base}/user")
        card = me.get_by_test_id("sub-card")
        expect(card.get_by_test_id("status-penwright")).to_have_text("ACTIVE")
        expect(card.get_by_test_id("deadline-line")).to_have_text(
            "Site says: trial ends Day 10 · Real last day to cancel: Day 7.")
        expect(card.get_by_test_id("risk-score")).to_contain_text("/100")
        expect(card.get_by_test_id("view-review")).to_have_text("View fine-print review")
        step("Priya's dashboard: subscription card with the Day 10 vs Day 7 line, risk, Keep / Cancel")

        dash.bring_to_front()
        dash.get_by_test_id("sim-jump-5").click()
        toast = dash.get_by_test_id("toast-alert").filter(has_text="Your Penwright trial ends on Day 10")
        expect(toast).to_be_visible()
        check = dash.get_by_test_id("alert-trial-check")
        expect(check).to_contain_text("Your Penwright trial ends on Day 10, but your real last day to cancel is Day 7. "
                                      "You've opened it twice. Do you want to keep it?")
        step("Day 5 (control room): toast + check-in alert")

        me.bring_to_front()
        me.reload()
        reminder = me.get_by_test_id("user-reminder")
        expect(reminder.get_by_test_id("reminder-usage")).to_contain_text("Opened twice in 5 days (last on Day 4).")
        expect(reminder.get_by_test_id("reminder-advice")).to_contain_text("SubGuard suggests: cancel. You decide.")
        me.get_by_test_id("chat-open").click()
        me.get_by_test_id("chat-input").fill("Should I keep Penwright?")
        me.get_by_test_id("chat-send").click()
        expect(me.locator("#chat-log")).to_contain_text("the first paid year costs $524.88")
        shot(me, "02_checkin_and_chat")
        me.locator("#chat-close").click()
        step("Day 5 (Priya): usage summary, advice labelled 'You decide', chat answers with $524.88")

        reminder.get_by_test_id("alert-cancel").click()
        confirm = me.get_by_test_id("confirm-card")
        expect(confirm).to_contain_text("$524.88/yr")
        confirm.get_by_test_id("confirm-button").click()
        email = me.get_by_test_id("email-preview")
        expect(email.get_by_test_id("email-paypal-done")).to_have_text("Cancelled in PayPal. You won't be charged.")
        expect(me.get_by_test_id("toast-result")).to_have_count(0)  # no extra pop-ups in the cancel flow
        body = email.get_by_test_id("email-body")
        expect(body).to_have_value(re.compile("at least 3 days before the next billing date"))
        shot(me, "03_email_preview")
        email.get_by_test_id("email-to").fill("")
        expect(email.get_by_test_id("email-send")).to_be_disabled()
        email.get_by_test_id("email-to").fill("cancel@penwright.example")
        body.fill(body.input_value() + "\nEdited by Priya.")
        ctx.route("https://mail.google.com/**", lambda route: route.fulfill(body="Gmail stub"))
        with ctx.expect_page() as gmail_info:
            email.get_by_test_id("email-open-gmail").click()
        gmail = gmail_info.value
        gmail.wait_for_load_state()
        assert gmail.url.startswith("https://mail.google.com/mail/?view=cm") and "Edited%20by%20Priya." in gmail.url
        gmail.close()
        expect(email.get_by_test_id("email-sent")).to_have_text("Opened in Gmail (demo)")
        email.get_by_test_id("email-dismiss").click()
        expect(me.get_by_test_id("toast-result")).to_have_count(0)
        expect(card.get_by_test_id("status-penwright")).to_have_text("CANCELLED")
        expect(me.get_by_test_id("sub-cancel")).to_have_count(0)
        expect(me.get_by_test_id("user-protected")).to_contain_text("$524.88/yr")
        me.get_by_test_id("nav-emails").click()  # sidebar sections (D-122)
        expect(me.get_by_test_id("cancellation-notice").first).to_be_visible()
        expect(me.get_by_test_id("cancellation-notice").first).to_contain_text("edited: yes")
        expect(me.get_by_test_id("panel-overview")).to_be_hidden()
        expect(me).to_have_url(re.compile("#emails$"))
        me.get_by_test_id("nav-overview").click()
        expect(me.get_by_text("Restart trial")).to_have_count(0)
        shot(me, "03_cancelled")
        step("Cancel: reminder -> confirmation card -> email preview (no toasts) -> CANCELLED, $524.88/yr")

        dash.bring_to_front()
        expect(dash.locator("#kpi-protected")).to_have_text("$524.88/yr", timeout=12000)
        expect(dash.get_by_test_id("alert-done")).to_contain_text("Cancelled in PayPal. You won't be charged.")
        expect(dash.get_by_text("Restart trial")).to_have_count(0)
        dash.get_by_test_id("sim-jump-11").click()
        expect(dash.get_by_test_id("blocked-charge").first).to_contain_text("First charge due today: blocked")
        step("Day 11 (control room): blocked charge, Money protected $524.88/yr")

        me.bring_to_front()
        me.reload()
        expect(me.get_by_test_id("proof-banner")).to_have_text(
            "First charge due today: blocked. No active PayPal subscription.")
        me.get_by_test_id("nav-analytics").click()
        for chart in ("chart-cost", "chart-usage", "chart-risk"):
            expect(me.get_by_test_id(chart).locator("canvas").first).to_be_visible()
        box = me.get_by_test_id("chart-cost").bounding_box()
        assert box and box["width"] > 200, f"chart not sized after its section opened: {box}"
        shot(me, "03a_user_analytics")
        me.get_by_test_id("nav-history").click()
        hist = me.get_by_test_id("user-history")
        expect(hist).to_contain_text("Penwright Studio")
        expect(hist).to_contain_text("Cancelled in PayPal on Day 5 by you")
        me.get_by_test_id("history-search").fill("no such merchant")
        expect(hist).not_to_contain_text("Penwright Studio")
        me.get_by_test_id("history-clear").click()
        expect(hist).to_contain_text("Penwright Studio")
        me.get_by_test_id("nav-overview").click()
        dates = me.get_by_test_id("key-dates")
        expect(dates.first).to_be_hidden()  # key dates stay folded until she opens them
        me.get_by_test_id("key-dates-toggle").first.locator("summary").click()
        expect(dates.first).to_be_visible()
        shot(me, "03b_user_dashboard")
        me.get_by_test_id("theme-toggle").click()
        expect(me.locator("html")).to_have_attribute("data-theme", "light")
        expect(me.locator("html")).to_have_attribute("data-ag-theme-mode", "light")
        me.reload()
        expect(me.get_by_test_id("theme-toggle")).to_contain_text("Light")  # remembered
        shot(me, "03c_user_dashboard_light")
        me.get_by_test_id("theme-toggle").click()
        expect(me.locator("html")).to_have_attribute("data-theme", "dark")
        step("Day 11 (Priya): proof banner, sidebar sections, AG Charts, history grid + search, key dates, theme")

        dash.bring_to_front()
        expect(dash.get_by_test_id("audit-chain")).to_contain_text("chain verified")
        summary = dash.get_by_test_id("audit-summary")
        expect(summary).to_contain_text("Allowed the cancel")
        expect(summary).to_contain_text("First charge due: blocked")
        expect(dash.get_by_test_id("audit-log-export")).to_be_hidden()  # full log folded away (D-121)
        dash.get_by_test_id("audit-full-toggle").click()
        with dash.expect_download() as dl_info:
            dash.get_by_test_id("audit-log-export").click()
        csv_text = Path(dl_info.value.path()).read_text(encoding="utf-8")
        assert "paypal_cancel" in csv_text and "R1" in csv_text, "CSV export missing rows"
        step(f"audit log CSV exported ({len(csv_text.splitlines())} lines), chain verified")

        sub_id = next(s["id"] for s in httpx.get(f"{base}/api/subscriptions?user=priya").json()
                      if s["plan_key"] == "penwright-pro")
        page = watch(ctx.new_page())
        page.goto(f"{base}/subscriptions/{sub_id}?user=priya")
        expect(page.get_by_test_id("risk-score")).to_contain_text("/100")
        expect(page.get_by_test_id("finding-PROMPT_INJECTION_ATTEMPT").first).to_be_visible()
        expect(page.get_by_test_id("cancellation-notice")).to_contain_text("Opened in Gmail (demo)")
        page.get_by_test_id("email-review").click()
        expect(page.get_by_test_id("email-sent")).to_be_visible()  # already handed over: shows the sent email
        page.get_by_test_id("email-dismiss").click()
        expect(page.locator("#sub-audit-grid .ag-row").first).to_be_visible()
        shot(page, "04_subscription")
        step("subscription page: findings grid, notice, audit entries")
        browser.close()


def autoplay(base: str, headed: bool) -> None:
    """The "Start demo" button: runs to the check-in, pauses for Priya, then finishes. All three answers."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        dash = watch(browser.new_page(viewport={"width": 1440, "height": 1000}))
        dash.goto(f"{base}/")
        start = dash.get_by_test_id("demo-start")
        for answer, expected, outcome in (("cancel", "$524.88", "Cancelled Day 5"),
                                          ("keep", "Kept on purpose", "Kept"),
                                          ("skip", "$524.88", "Auto-cancelled Day 6 (R2)")):
            start.click()
            dlg = dash.get_by_test_id("decision-dialog")
            expect(dlg).to_be_visible(timeout=40000)
            expect(dlg).to_contain_text("but your real last day to cancel is Day 7. You've opened it twice.")
            expect(dash.get_by_test_id("step-read")).to_contain_text("Risk 87 · cancel by Day 7")
            if answer == "cancel":
                shot(dash, "05_autoplay_ask")
            dash.get_by_test_id(f"decision-{answer}").click()
            if answer == "cancel":
                card = dash.locator("#confirm-dialog").get_by_test_id("confirm-card")
                expect(card).to_contain_text("$524.88/yr")
                card.get_by_test_id("confirm-button").click()
                email = dash.get_by_test_id("email-preview")
                email.get_by_test_id("email-send").click()
                expect(email.get_by_test_id("email-sent")).to_have_text("Email sent (demo)")
                email.get_by_test_id("email-dismiss").click()
            done = dash.get_by_test_id("pipeline-done")
            expect(done).to_contain_text(expected, timeout=40000)
            expect(dash.get_by_test_id("step-outcome")).to_contain_text(outcome)
            expect(dash.get_by_test_id("demo-day")).to_have_text("11")
            if answer == "cancel":
                expect(dash.locator("#kpi-protected")).to_have_text("$524.88/yr")
                shot(dash, "06_autoplay_done")
            if answer == "skip":
                expect(dash.get_by_test_id("email-ready")).to_contain_text("ready to review and send")
            expect(start).to_be_enabled()
            step(f"Start demo -> paused at the check-in -> {answer} -> {outcome}")
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
        story(base, args.headed)
        autoplay(base, args.headed)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(10)
        if data is not None:
            shutil.rmtree(data, ignore_errors=True)
    if errors:
        print("Console/page errors:\n  " + "\n  ".join(errors))
        return 1
    print("UI check passed: the demo story in the browser, no console errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

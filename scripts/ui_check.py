"""Browser check: the demo story (Priya + Penwright) in mock mode, driven through the real UI with Playwright.

Starts its own mock server on a free port with a throwaway DATA_DIR (unless --base-url is given), then (Phase 3):
`/` empty state + presenter bar (D key) -> shop (U20) -> companion (verdict, 3 things, PayPal check, evidence
folded) -> merchant welcome only (U22) -> Priya's card (cost line, act-by, dots, Verified with PayPal) -> Day 5
check-in band on the card (one Keep / Cancel pair, U8) + chat -> "Cancel Penwright trial? You won't be charged
$24.99" -> email preview (clause highlighted, Open in my email app) -> Day 11 proof -> audit drawer
(routine hidden, CSV) -> theme -> evidence page tabs (U23-U25). Then 390 px layout (U27), Start demo with all three
answers on the card, and Quillnote (Layer 2: ACTION NEEDED on the card, polled until CANCELLED).
Fails on any console error, page error or CDN request (U30).

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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from playwright.sync_api import Browser, BrowserContext, Page, expect, sync_playwright
from signin import add_session, demo_password, http_client, session_cookie

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []
SHOTS: Path | None = None
SESSION = ""  # Priya's sg_session cookie (Phase 7: pages need sign-in), set in main()
HTTP: httpx.Client | None = None  # API calls with that cookie


def on(days: int) -> str:
    """Calendar date `days` after a sign-up made now, as SubGuard writes it ("Nov 18")."""
    d = datetime.now(UTC) + timedelta(days=days)
    return f"{d:%b} {d.day}"


ACT_BY = f"Act by {on(7)} (the terms allow {on(8)})"  # D6
PROOF = "Checked PayPal: no active subscription, so no charge can be taken."  # B8


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


def api() -> httpx.Client:
    assert HTTP is not None, "main() signs in first"
    return HTTP


def context(browser: Browser, base: str, **kw: object) -> BrowserContext:
    """A browser context already signed in as Priya."""
    ctx = browser.new_context(**kw)  # type: ignore[arg-type]
    add_session(ctx, base, SESSION)
    return ctx


def start_server(password: str) -> tuple[subprocess.Popen[bytes], str, Path]:
    data = Path(tempfile.mkdtemp(prefix="subguard-ui-"))
    shutil.copytree(ROOT / "data" / "seed", data / "seed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "APP_MODE": "mock", "DATA_DIR": str(data), "DEMO_SEED": "true", "DEMO_PASSWORD": password}
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


def no_cdn(ctx: object) -> None:
    """U30: AG Grid / AG Charts come from /static/vendor; any request to a CDN is an error."""
    def check(req: object) -> None:
        url = getattr(req, "url", "")
        if "cdn.jsdelivr.net" in url or "unpkg.com" in url:
            errors.append(f"CDN request (U30): {url}")
    ctx.on("request", check)  # type: ignore[attr-defined]


def ready(page: Page) -> None:
    """U29: the page reports data-ready=1 once no count-up is running."""
    expect(page.locator("html")).to_have_attribute("data-ready", "1", timeout=5000)


def expand(card: object) -> None:
    """D-170: each subscription is a dropdown; open it (once) to reach its details."""
    fold = card.get_by_test_id("sub-toggle")  # type: ignore[attr-defined]
    if fold.get_attribute("open") is None:
        fold.get_by_test_id("sub-row").click()
    expect(fold).to_have_attribute("open", "")


def one_pair(page: Page) -> None:
    """U8: only one Keep / Cancel pair on the screen."""
    keep = page.locator("[data-sub-keep]:visible, [data-action=keep]:visible")
    cancel = page.locator("[data-sub-cancel]:visible, [data-action=cancel]:visible")
    assert keep.count() <= 1 and cancel.count() <= 1, (keep.count(), cancel.count())


def story(base: str, headed: bool) -> None:
    api().post("/api/demo/reset", timeout=30).raise_for_status()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = context(browser, base, viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        no_cdn(ctx)
        me = watch(ctx.new_page())
        me.goto(f"{base}/")
        expect(me.get_by_test_id("user-empty")).to_contain_text("All clear")  # U11, D-174
        expect(me.get_by_test_id("empty-open-shop")).to_be_visible()
        expect(me.get_by_test_id("user-protected")).to_be_hidden()  # no zero KPIs
        expect(me.get_by_test_id("demo-bar")).to_have_count(0)  # D-167: the controls live on the Live demo page
        me.keyboard.press("d")
        expect(me.get_by_test_id("demo-bar")).to_have_count(0)
        bar = me.locator(".topbar")
        for gone in ("nav-tabs", "view-shop", "health-dots"):
            expect(bar.get_by_test_id(gone)).to_have_count(0)
        for there in ("brand", "mode-badge", "chat-open", "theme-toggle", "user-avatar", "topnav-presenter",
                      "topnav-dashboard"):
            expect(bar.get_by_test_id(there)).to_be_visible()
        bar.get_by_test_id("topnav-presenter").locator("summary").click()  # D-174: Live demo / Demo shops
        for there in ("topnav-demo", "topnav-shop"):
            expect(bar.get_by_test_id(there)).to_be_visible()
        expect(bar.get_by_test_id("topnav-shop")).to_have_attribute("href", "/shop?user=priya")  # D-166
        me.keyboard.press("Escape")
        me.get_by_test_id("dev-menu").locator("summary").click()
        expect(me.get_by_test_id("dev-docs")).to_be_visible()
        ready(me)
        step("`/` empty: one friendly card, no KPIs, no demo controls, top bar with the three links")

        dash = watch(ctx.new_page())  # the presenter's window
        dash.goto(f"{base}/?demo=1")
        expect(dash.get_by_test_id("topnav-demo")).to_have_attribute("aria-current", "page")
        expect(dash.get_by_test_id("user-dashboard")).to_have_count(0)  # D-167: only the Live demo
        expect(dash.get_by_test_id("demo-start")).to_be_visible()
        expect(dash.get_by_test_id("demo-priya-empty")).to_be_visible()
        with ctx.expect_page() as shop_info:
            dash.get_by_test_id("demo-open-shop").click()
        shop = watch(shop_info.value)
        shop.wait_for_load_state()
        expect(shop.get_by_test_id("shop-features")).to_be_visible()  # U20
        shop.get_by_test_id("shop-terms-toggle").click()

        def slow(route: object) -> None:  # hold the review back so the "checking" title can be read
            time.sleep(0.8)
            route.continue_()  # type: ignore[attr-defined]

        shop.route("**/api/review/preflight", slow)
        shop.get_by_test_id("shop-paypal-btn").click()
        expect(shop.get_by_test_id("companion-title")).to_have_text("SubGuard is checking this offer…")  # D-170
        risk = shop.get_by_test_id("companion-risk")
        expect(risk).to_be_visible(timeout=20000)
        score = int(re.search(r"(\d+)/100", risk.inner_text()).group(1))  # type: ignore[union-attr]
        assert abs(score - 87) <= 5, score
        expect(shop.get_by_test_id("companion-verdict")).to_have_text(f"$0 today, then $24.99/month from {on(11)}")
        expect(shop.get_by_test_id("companion-verdict-sub")).to_have_text(
            "Rises to $49.99 after 3 months · up to $524.88 in year one")
        things = shop.get_by_test_id("companion-things").locator("li")
        expect(things).to_have_count(3)
        for t in ("NOTICE_PERIOD", "TERMS_MISMATCH", "PROMPT_INJECTION_ATTEMPT"):
            expect(shop.get_by_test_id(f"finding-{t}").first).to_be_visible()
        expect(shop.get_by_test_id("finding-TERMS_MISMATCH")).to_contain_text(
            f"The page says $0 today. The PayPal plan charges $24.99 on {on(11)}.")
        expect(shop.get_by_test_id("finding-PROMPT_INJECTION_ATTEMPT")).to_have_text(
            re.compile("Hidden instructions to AI found on this page and ignored."))
        ev = shop.get_by_test_id("companion-evidence")
        expect(ev.locator("summary")).to_contain_text("Show evidence (8 quoted clauses, cross-check table)")
        expect(shop.get_by_test_id("companion-summary")).to_be_hidden()  # U15: folded by default
        ev.locator("summary").click()
        expect(ev.locator("tr").first).to_contain_text("The headline says")  # U16: failing row first
        expect(ev).to_contain_text("Price $24.99 shown only in fine print")
        expect(shop.get_by_test_id("companion-promise")).to_have_text("I'll check with you before your trial runs out.")
        act_by = shop.get_by_test_id("companion-date-act_by")  # B2/D6: dates, never "Day 7"; D-170: Key dates tiles
        expect(act_by).to_contain_text(on(7))
        expect(act_by).to_contain_text(f"terms allow {on(8)}")
        expect(shop.get_by_test_id("companion-date-first_charge")).to_contain_text(on(11))
        expect(shop.get_by_test_id("companion-title")).to_have_text("SubGuard checked this offer")
        expect(shop.get_by_test_id("companion-auto-send")).not_to_be_checked()  # D7: opt-in, unticked
        shot(shop, "01_companion")
        shop.get_by_test_id("companion-continue").click()
        expect(shop.get_by_test_id("shop-welcome")).to_contain_text("You're subscribed. Welcome to Penwright.")
        expect(shop.get_by_test_id("shop-open-subguard")).to_be_visible(timeout=15000)
        expect(shop.get_by_test_id("paypal-subscribed")).to_have_count(0)  # U22: no PayPal debug card on the shop
        expect(shop.get_by_test_id("shop-paypal-btn")).to_have_count(0)
        step(f"Day 0: companion risk {score}, verdict + 3 things + PayPal check, evidence folded; shop: welcome only")

        me.bring_to_front()
        me.reload()
        card = me.get_by_test_id("sub-card")
        expect(card.get_by_test_id("status-penwright")).to_have_text("ACTIVE")
        expect(card.get_by_test_id("sub-headline")).to_have_text(f"Free until {on(10)}, then $24.99/month")  # D-169
        expect(card.get_by_test_id("sub-line")).to_be_hidden()  # D-170: a closed dropdown until opened
        expand(card)
        expect(card.get_by_test_id("sub-line")).to_have_text("Up to $524.88 this year if you keep it.")  # D-177
        expect(card.get_by_test_id("my-plan-text")).to_have_text(
            f"I'll check in with you on {on(5)}. No answer? I'll cancel it in PayPal on {on(6)}, "
            f"a day before your {on(7)} deadline.")
        expect(card.get_by_test_id("tl-check_in")).to_contain_text(on(5))
        expect(card.get_by_test_id("tl-auto_cancel")).to_contain_text("if no answer")
        expect(card.get_by_test_id("tl-act_by")).to_contain_text(on(7))
        expect(card.get_by_test_id("tl-act_by")).to_have_class(re.compile("is-key"))
        expect(card.get_by_test_id("tl-today")).to_have_text("Today")
        expect(card.get_by_test_id("view-review")).to_have_text("See evidence")
        expect(me.get_by_test_id("next-decision")).to_have_count(0)  # D-169: no Next decision card
        expect(me.get_by_test_id("audit-summary-row").first).to_be_visible()  # B3
        expect(me.get_by_test_id("key-dates")).to_have_count(0)  # U7: the dots replace the Key dates box
        pp = card.get_by_test_id("paypal-verified")
        expect(pp.locator("summary")).to_contain_text("Verified with PayPal ✓")
        pp.locator("summary").click()
        expect(pp.get_by_test_id("paypal-status")).to_have_text("ACTIVE")
        expect(pp).not_to_contain_text("PayPal-Request-Id")  # U4: ids are on the evidence page
        one_pair(me)
        ready(me)
        shot(me, "02_card")
        card.get_by_test_id("change-plan").click()  # D-177: opens Settings
        expect(me.get_by_test_id("panel-settings")).to_be_visible()
        me.get_by_test_id("nav-overview").click()
        step("Priya's card (trial): headline, My plan, one sub-line, Cancel / Keep, timeline with Today, Change plan")

        dash.bring_to_front()
        dash.get_by_test_id("sim-jump-5").click()
        toast = dash.get_by_test_id("toast-alert").filter(has_text=f"Your Penwright trial ends on {on(10)}")
        expect(toast).to_be_visible()
        box = toast.bounding_box()  # B5: top right, under the top bar
        assert box and box["x"] > 1440 / 2 and box["y"] < 300, f"toast not top right: {box}"
        expect(dash.get_by_test_id("step-ask")).to_have_class(re.compile("is-done"))  # B4: ticks by hand
        expect(dash.get_by_test_id("sim-jump-0")).to_be_disabled()  # days only move forward
        step("Day 5 (presenter): toast top right, steps tick, past days disabled")

        me.bring_to_front()
        me.reload()
        reminder = card.get_by_test_id("user-reminder")  # D-170: opens by itself, she has to decide
        expect(card.get_by_test_id("sub-toggle")).to_have_attribute("open", "")
        expect(card.get_by_test_id("sub-headline")).to_have_text("Keep your Penwright trial?")  # D-169
        expect(reminder.get_by_test_id("reminder-usage")).to_have_text("You opened it twice in 5 days.")
        expect(reminder.get_by_test_id("reminder-advice")).to_have_text("SubGuard suggests cancelling; you decide.")
        expect(card.get_by_test_id("my-plan-text")).to_contain_text(f"I'll cancel it in PayPal on {on(6)}")
        expect(card.get_by_test_id("tl-check_in")).to_contain_text("Checked in")
        expect(card.get_by_test_id("sub-cancel")).to_have_count(0)
        one_pair(me)
        me.get_by_test_id("chat-open").click()
        me.get_by_test_id("chat-input").fill("Should I keep Penwright?")
        me.get_by_test_id("chat-send").click()
        expect(me.locator("#chat-log")).to_contain_text("the first paid year costs $524.88")
        me.get_by_test_id("chat-chip-nothing").click()  # B11: chips with scripted answers
        expect(me.locator("#chat-log")).to_contain_text(f"cancels Penwright Studio in PayPal on {on(6)}")
        shot(me, "02_checkin_and_chat")
        me.locator("#chat-close").click()
        step("Day 5 (Priya): the card asks 'Keep your Penwright trial?', one Keep / Cancel pair, chat answers")

        card.get_by_test_id("alert-cancel").click()
        confirm = me.get_by_test_id("confirm-card")
        expect(confirm.locator("h3")).to_have_text("Cancel Penwright trial?")  # U12
        expect(confirm).to_contain_text(f"You won't be charged $24.99 on {on(11)}.")
        expect(confirm).not_to_contain_text("/yr")
        expect(confirm).not_to_contain_text("can't be undone")
        confirm.get_by_test_id("confirm-button").click()
        email = me.get_by_test_id("email-preview")
        expect(email.get_by_test_id("email-paypal-done")).to_have_text("Cancelled in PayPal. You won't be charged.")
        expect(me.get_by_test_id("toast-result")).to_have_count(0)  # no extra pop-ups in the cancel flow
        body = email.get_by_test_id("email-body")
        expect(body).to_have_value(re.compile("at least 3 days before the next billing date"))
        expect(email.get_by_test_id("email-clause").first).to_contain_text("at least 3 days before")  # U13
        expect(email.get_by_test_id("email-open-app")).to_have_text("Open in my email app")
        shot(me, "03_email_preview")
        email.get_by_test_id("email-to").fill("")
        expect(email.get_by_test_id("email-send")).to_be_disabled()
        expect(email.get_by_test_id("email-open-app")).to_be_disabled()
        email.get_by_test_id("email-to").fill("cancel@penwright.example")
        body.fill(body.input_value() + "\nEdited by Priya.")
        expect(email.get_by_test_id("email-open-gmail")).to_have_count(0)  # no email brand on screen (D-165)
        me.evaluate("""() => { const click = HTMLAnchorElement.prototype.click;  // catch the mailto: hand-off
          HTMLAnchorElement.prototype.click = function () {
            if (this.href.startsWith("mailto:")) { window.__mailto = this.href; return; }
            return click.call(this); }; }""")
        email.get_by_test_id("email-open-app").click()
        mailto = me.evaluate("() => window.__mailto")
        assert mailto.startswith("mailto:cancel@penwright.example?subject=") and "Edited%20by%20Priya." in mailto
        expect(email.get_by_test_id("email-sent")).to_have_text("Opened in your email app (demo)")
        email.get_by_test_id("email-dismiss").click()
        expect(me.get_by_test_id("toast-result")).to_have_count(0)
        expect(card.get_by_test_id("status-penwright")).to_have_text("CANCELLED")
        expand(card)
        expect(card.get_by_test_id("sub-headline")).to_have_text("You won't be charged")  # D-169
        expect(card.get_by_test_id("sub-line")).to_have_text("$24.99 saved now · up to $524.88 this year")
        expect(card.get_by_test_id("card-saved")).to_have_text("$24.99")  # D10: the charge avoided, merged in
        expect(card.get_by_test_id("risk-score")).to_have_text(re.compile(r"^Risk was \d+$"))
        for key, text in (("cancelled", "Cancelled"), ("email", "Email sent"), ("first_charge", "blocked")):
            expect(card.get_by_test_id(f"tl-{key}")).to_contain_text(text)
        expect(card.get_by_test_id("start-new-trial")).to_have_count(0)  # D-172: one Penwright per run
        expect(me.get_by_test_id("sub-cancel")).to_have_count(0)
        ready(me)  # U29: the count-up has finished
        me.get_by_test_id("nav-emails").click()
        expect(me.get_by_test_id("cancellation-notice").first).to_contain_text("edited: yes")
        expect(me.get_by_test_id("panel-overview")).to_be_hidden()
        expect(me).to_have_url(re.compile("#emails$"))
        me.get_by_test_id("nav-overview").click()
        expect(me.get_by_text("Restart trial")).to_have_count(0)
        shot(me, "03_cancelled")
        step("Cancel: card -> 'Cancel Penwright trial? You won't be charged $24.99' -> email (clause highlighted)")

        dash.bring_to_front()
        dash.get_by_test_id("sim-jump-11").click()
        expect(dash.get_by_test_id("step-proof")).to_have_class(re.compile("is-done"))
        expect(dash.get_by_test_id("proof-banner")).to_have_text(f"First charge due today. {PROOF}")
        me.bring_to_front()  # D-167: the Activity tab is on Priya's dashboard, not the Live demo page
        me.reload()
        expect(card.get_by_test_id("sub-headline")).to_have_text("$24.99 never charged")  # D-169: the proof state
        expect(card.get_by_test_id("tl-first_charge")).to_have_class(re.compile("is-key"))
        expect(me.get_by_test_id("proof-banner")).to_have_count(0)
        me.get_by_test_id("nav-activity").click()
        acts = me.get_by_test_id("activity-list")  # D-172: ONE timeline, newest first
        kinds = [e.get_attribute("data-kind") for e in acts.get_by_test_id("tl-entry").all()]
        assert kinds == ["charge_blocked", "email_sent", "cancel", "checkin", "timer", "signup", "review"], kinds
        expect(acts.locator("[data-kind=checkin]")).to_contain_text("You chose: Cancel")
        cancel = acts.locator("[data-kind=cancel]")
        expect(cancel).to_contain_text("Cancelled your Penwright subscription")
        expect(cancel.get_by_test_id("tl-proof-body")).to_be_hidden()
        cancel.get_by_test_id("tl-proof").click()  # Proof ▸ opens inline
        expect(cancel.get_by_test_id("tl-proof-body")).to_contain_text("ACTIVE → CANCELLED")
        expect(acts).not_to_contain_text("edited:")
        expect(me.get_by_test_id("activity-raw-log")).to_be_visible()
        shot(me, "03_activity")
        me.get_by_test_id("nav-overview").click()
        dash.bring_to_front()
        step("Day 11: proof on the Live demo and Priya's dashboard; her Activity is one timeline with Proof")

        did = dash.get_by_test_id("audit-summary")
        expect(did.get_by_test_id("audit-summary-row")).to_have_count(5)
        expect(did).to_contain_text("Checked PayPal: no active subscription")
        mine = me.get_by_test_id("audit-summary")  # D-169: Priya's short, dated lines
        expect(mine.get_by_test_id("audit-summary-row")).to_have_count(3)  # D-172: the 3 latest Activity entries
        expect(mine.get_by_test_id("audit-summary-row").first).to_contain_text("nothing to charge")
        expect(mine).not_to_contain_text("edited:")
        dash.get_by_test_id("audit-full-toggle").click()
        drawer = dash.get_by_test_id("audit-drawer")
        expect(drawer).to_be_visible()
        expect(drawer.get_by_test_id("audit-chain")).to_contain_text("chain verified")
        grid = drawer.get_by_test_id("audit-log-grid")
        expect(grid.locator(".ag-row").first).to_be_visible()
        expect(grid).not_to_contain_text("verify_subscription")  # U26: routine reads hidden by default
        drawer.get_by_test_id("audit-routine").check()
        drawer.get_by_test_id("audit-filter").fill("paypal_call")
        expect(grid.locator(".ag-row").first).to_be_visible()
        drawer.get_by_test_id("audit-filter").fill("")
        with dash.expect_download() as dl_info:
            drawer.get_by_test_id("audit-log-export").click()
        csv_text = Path(dl_info.value.path()).read_text(encoding="utf-8")
        assert "paypal_cancel" in csv_text and "R1" in csv_text, "CSV export missing rows"
        dash.keyboard.press("Escape")
        expect(drawer).to_be_hidden()
        step(f"audit drawer: chain verified, routine hidden, CSV exported ({len(csv_text.splitlines())} lines)")

        me.bring_to_front()
        me.get_by_test_id("theme-toggle").click()
        expect(me.locator("html")).to_have_attribute("data-theme", "light")
        expect(me.locator("html")).to_have_attribute("data-ag-theme-mode", "light")
        me.reload()
        expect(me.get_by_test_id("theme-toggle")).to_have_attribute("title", "Switch to dark theme")  # remembered
        shot(me, "03c_user_dashboard_light")
        me.get_by_test_id("theme-toggle").click()
        expect(me.locator("html")).to_have_attribute("data-theme", "dark")

        sub_id = next(s["id"] for s in api().get("/api/subscriptions?user=priya").json()
                      if s["plan_key"] == "penwright-pro")
        page = watch(ctx.new_page())
        page.goto(f"{base}/subscriptions/{sub_id}?user=priya")
        expect(page.get_by_test_id("risk-score")).to_contain_text("/100")
        expect(page.get_by_test_id("ev-tab-summary")).to_have_attribute("aria-selected", "true")  # U23
        expect(page.get_by_test_id("ev-verdict")).to_contain_text("3 things to know")
        for chart in ("chart-cost", "chart-usage", "chart-risk"):  # U25: charts on the evidence page
            expect(page.get_by_test_id(chart).locator("canvas").first).to_be_visible()
        expect(page.get_by_test_id("cancellation-notice")).to_contain_text("Opened in your email app (demo)")
        page.get_by_test_id("email-review").click()
        expect(page.get_by_test_id("email-sent")).to_be_visible()  # already handed over: shows the sent email
        page.get_by_test_id("email-dismiss").click()
        shot(page, "04_subscription")
        page.get_by_test_id("ev-tab-evidence").click()
        expect(page.get_by_test_id("finding-PROMPT_INJECTION_ATTEMPT").first).to_have_text("Hidden instructions to AI")
        expect(page.get_by_test_id("findings-grid")).not_to_contain_text("NOTICE_PERIOD")  # U24: plain labels
        expect(page.get_by_test_id("findings-grid")).not_to_contain_text("paypal_check")
        page.get_by_test_id("ev-tab-paypal").click()
        expect(page.get_by_test_id("crosscheck-table").locator("tbody tr").first).to_have_class("row-bad")
        expect(page.get_by_test_id("ev-paypal-card").get_by_test_id("paypal-status")).to_have_text("CANCELLED")
        page.get_by_test_id("ev-tab-activity").click()
        expect(page.get_by_test_id("ev-activity")).to_contain_text("Cancelled your subscription")
        page.get_by_test_id("ev-raw-log").locator("summary").click()
        expect(page.locator("#sub-audit-grid .ag-row").first).to_be_visible()
        step("evidence page: Summary (verdict, charts), Evidence (plain labels), PayPal check (fail first), Activity")
        browser.close()


def mobile(base: str, headed: bool) -> None:
    """U27: at 390 px the top bar is one line, sections are a bottom tab bar, nothing scrolls sideways; the companion
    is a bottom sheet."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = watch(context(browser, base, viewport={"width": 390, "height": 844}).new_page())
        page.goto(f"{base}/")
        bar = page.locator(".topbar").bounding_box()
        assert bar and bar["height"] <= 100, f"top bar taller than logo row + nav row at 390 px: {bar}"  # D-166
        for t in ("topnav-presenter", "topnav-dashboard", "user-avatar"):
            nb = page.get_by_test_id(t).bounding_box()
            assert nb and nb["x"] >= 0 and nb["x"] + nb["width"] <= 390, (t, nb)
        nav = page.get_by_test_id("side-nav").bounding_box()
        assert nav and nav["y"] + nav["height"] >= 844 - 2 and nav["height"] < 80, f"no bottom tab bar: {nav}"
        width = page.evaluate("document.documentElement.scrollWidth")
        assert width <= 390, f"horizontal scroll at 390 px: {width}"
        cards = page.get_by_test_id("sub-card")
        if cards.count():
            box = cards.first.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, box
        page.goto(f"{base}/?demo=1")  # D-167: the Live demo page fits the phone too
        expect(page.get_by_test_id("demo-start")).to_be_visible()
        width = page.evaluate("document.documentElement.scrollWidth")
        assert width <= 390, f"horizontal scroll on the Live demo at 390 px: {width}"
        for t in ("demo-bar", "pipeline", "demo-priya"):
            box = page.get_by_test_id(t).bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, (t, box)
        page.goto(f"{base}/shop/penwright")
        page.get_by_test_id("shop-paypal-btn").click()
        card = page.get_by_test_id("companion-overlay")
        expect(page.get_by_test_id("companion-risk")).to_be_visible(timeout=20000)
        page.wait_for_timeout(400)  # the sheet's slide-up (0.25 s) has finished
        box = card.bounding_box()
        assert box and abs(box["y"] + box["height"] - 844) <= 2 and box["width"] >= 388, f"not a bottom sheet: {box}"
        page.keyboard.press("Escape")
        browser.close()
        step("390x844: top bar + nav row, bottom tab bar, no sideways scroll (dashboard and Live demo), bottom sheet")


def companion_in_view(base: str, headed: bool) -> None:
    """B1: when the companion opens, its risk badge is inside the viewport (it used to open scrolled down)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        for w, h in ((1440, 900), (390, 844)):
            page = watch(context(browser, base, viewport={"width": w, "height": h}).new_page())
            page.goto(f"{base}/shop/penwright")
            page.get_by_test_id("shop-paypal-btn").click()
            risk = page.get_by_test_id("companion-risk")
            expect(risk).to_be_visible(timeout=20000)
            box = risk.bounding_box()
            assert box and box["y"] >= 0 and box["y"] + box["height"] <= h, f"{w}x{h}: risk badge off screen {box}"
            card = page.get_by_test_id("companion-overlay").bounding_box()
            # +0.5 px: sub-pixel layout can report 720.00003 for a 720 px card (a flaky failure, Phase 5)
            assert card and card["height"] <= min(720, h) + 0.5, f"{w}x{h}: companion taller than allowed {card}"
            expect(page.get_by_test_id("companion-continue")).to_be_in_viewport()  # sticky footer
            page.keyboard.press("Escape")
            expect(page.get_by_test_id("companion-overlay")).to_have_count(0)
            page.close()
            step(f"companion at {w}x{h}: risk badge in view, footer buttons visible, Esc closes")
        browser.close()


def autoplay(base: str, headed: bool) -> None:
    """The "Start demo" button plays itself (D-168): it stops only for the order confirmation and for Priya's answer
    under Priya's side (U8); after a Cancel the confirmation card and the email Send happen by themselves."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        dash = watch(context(browser, base, viewport={"width": 1440, "height": 1000}).new_page())
        dash.goto(f"{base}/?demo=1")
        start = dash.get_by_test_id("demo-start")
        for answer, expected, outcome in (("cancel", "$24.99 charge never taken", f"Cancelled {on(5)}"),
                                          ("keep", "Kept on purpose", "Kept"),
                                          ("skip", "$24.99 charge never taken", f"Auto-cancelled {on(6)} (R2)")):
            start.click()
            order = dash.get_by_test_id("order-confirm")
            expect(order).to_be_visible(timeout=20000)
            expect(dash.get_by_test_id("order-text")).to_contain_text(f"$0 today, then $24.99/month from {on(11)}")
            expect(dash.get_by_test_id("step-approve")).to_contain_text("confirm the order")
            dash.get_by_test_id("order-approve").click()
            expect(order).to_be_hidden()
            band = dash.get_by_test_id("user-reminder")
            expect(band).to_be_visible(timeout=40000)
            expect(band).to_contain_text(f"{ACT_BY}. You've opened it twice")
            skip = dash.get_by_test_id("decision-skip")
            expect(skip).to_be_visible()
            expect(skip).to_have_text(f"Don't answer (SubGuard acts on {on(6)})")
            expect(dash.get_by_test_id("step-read")).to_contain_text(f"· act by {on(7)}")
            one_pair(dash)
            if answer == "cancel":
                shot(dash, "05_autoplay_ask")
                dash.get_by_test_id("alert-cancel").click()
                card = dash.locator("#confirm-dialog").get_by_test_id("confirm-card")
                expect(card).to_contain_text(f"You won't be charged $24.99 on {on(11)}.")
                email = dash.get_by_test_id("email-preview")  # no more clicks: it confirms and sends itself
                expect(email.get_by_test_id("email-sent")).to_have_text("Email sent (demo)", timeout=20000)
                expect(email).to_be_hidden(timeout=10000)
            elif answer == "keep":
                dash.get_by_test_id("alert-keep").click()
            else:
                skip.click()
            done = dash.get_by_test_id("pipeline-done")
            expect(done).to_contain_text(expected, timeout=40000)
            expect(dash.get_by_test_id("step-outcome")).to_contain_text(outcome)
            expect(dash.get_by_test_id("demo-day")).to_have_text("11")
            expect(skip).to_be_hidden()
            if answer == "cancel":
                expect(dash.get_by_test_id("user-avoided")).to_have_text("$24.99")
                # D-176: money saved -> a coin burst with "+$24.99 saved" at the final step
                expect(done.locator(".coin-plus")).to_have_text("+$24.99 saved", timeout=5000)
                shot(dash, "06_autoplay_done")
            if answer == "skip":
                expect(dash.get_by_test_id("user-email-ready")).to_contain_text("ready to review and send")
            expect(start).to_be_enabled()
            step(f"Start demo -> paused at the check-in under Priya's side -> {answer} -> {outcome}")
        browser.close()


def layer2(base: str, headed: bool) -> None:
    """A1/A2/A5: Quillnote (not a Fair Trial member). The AI finds the prose traps the basic check misses; Cancel
    gives the email draft + ACTION NEEDED on the card with the one-tap PayPal link; SubGuard polls until CANCELLED."""
    api().post("/api/demo/reset", timeout=30).raise_for_status()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = context(browser, base, viewport={"width": 1440, "height": 1000})
        shop = watch(ctx.new_page())
        shop.goto(f"{base}/shop/quillnote")
        expect(shop.get_by_test_id("demo-approval-note")).to_have_text("Demo: simulated PayPal approval")  # A6
        shop.get_by_test_id("shop-paypal-btn").click()
        risk = shop.get_by_test_id("companion-risk")
        expect(risk).to_be_visible(timeout=20000)
        score = int(re.search(r"(\d+)/100", risk.inner_text()).group(1))  # type: ignore[union-attr]
        assert 70 <= score <= 90, score
        expect(shop.get_by_test_id("finding-NOTICE_PERIOD").first).to_be_visible()
        expect(shop.get_by_test_id("companion-date-act_by")).to_contain_text(on(4))
        expect(shop.get_by_test_id("companion-date-act_by")).to_contain_text(f"terms allow {on(5)}")
        shop.get_by_test_id("companion-continue").click()
        expect(shop.get_by_test_id("shop-open-subguard")).to_be_visible(timeout=15000)
        step(f"Quillnote: companion risk {score}, notice in words read by the AI -> act by {on(4)}")

        sub_id = next(s["id"] for s in api().get("/api/subscriptions?user=priya").json()
                      if s["plan_key"] == "quillnote-plus")
        ev = watch(ctx.new_page())
        ev.goto(f"{base}/subscriptions/{sub_id}?user=priya")
        panel = ev.get_by_test_id("ai-vs-basic")
        expect(panel).to_contain_text("Only the AI found")
        expect(ev.get_by_test_id("avb-row-notice_period")).to_contain_text("✗ missed")
        expect(ev.get_by_test_id("avb-act-by")).to_contain_text("(too late)")
        shot(ev, "07_ai_vs_basic")
        ev.close()
        step("evidence page: AI vs basic check panel (notice period, step-up, hard cancel missed by the basic check)")

        me = watch(ctx.new_page())
        me.goto(f"{base}/me?user=priya")
        expect(me).to_have_url(re.compile(r"/\?user=priya$"))  # old URL redirects (U5)
        expect(me.get_by_test_id("mode-badge")).to_contain_text("Demo data")
        card = me.get_by_test_id("sub-card").filter(has=me.get_by_test_id("status-quillnote"))
        expand(card)
        card.get_by_test_id("sub-cancel").click()
        me.locator("#confirm-dialog").get_by_test_id("confirm-button").click()
        email = me.get_by_test_id("email-preview")
        expect(email).to_contain_text("Quillnote's terms ask for written notice")
        expect(email.get_by_test_id("email-paypal-done")).to_have_count(0)  # nothing was cancelled in PayPal yet
        email.get_by_test_id("email-send").click()
        expect(email.get_by_test_id("email-sent")).to_have_text("Email sent (demo)")
        email.get_by_test_id("email-dismiss").click()
        need = card.get_by_test_id("action-needed")
        expect(need).to_be_visible(timeout=10000)
        expect(card.get_by_test_id("sub-headline")).to_have_text("ACTION NEEDED: cancel Quillnote in PayPal")
        expect(need.get_by_test_id("layer2-waiting")).to_be_visible()
        expect(card.get_by_test_id("sub-cancel")).to_have_count(0)  # no Keep / Cancel while the handoff is open
        expect(card.get_by_test_id("timer-chip")).to_have_count(0)
        shot(me, "08_layer2_action_needed")
        step("Cancel -> email draft (sent) -> ACTION NEEDED on the card, no Keep / Cancel, waiting for PayPal")

        with ctx.expect_page() as pp_info:
            need.get_by_test_id("action-autopay").click()
        pp = watch(pp_info.value)
        pp.wait_for_load_state()
        expect(pp.get_by_test_id("autopay-demo-note")).to_be_visible()
        pp.get_by_test_id("autopay-row-quillnote").get_by_test_id("autopay-cancel").click()
        expect(pp.get_by_test_id("autopay-cancelled")).to_be_visible()
        pp.close()
        me.bring_to_front()
        expect(me.get_by_test_id("action-needed")).to_have_count(0, timeout=20000)
        expect(me.get_by_test_id("toast-layer2").first).to_be_visible()
        # D-174: done, so it leaves "Needs your attention" ("All clear ✓"); the Subscriptions list shows it cancelled
        expect(me.get_by_test_id("user-empty")).to_contain_text("All clear", timeout=10000)
        me.get_by_test_id("nav-subscriptions").click()
        row = me.locator('[data-testid=subs-row][data-merchant="Quillnote"]')
        expect(row.get_by_test_id("subs-status")).to_have_text("Cancelled")
        expect(row.get_by_test_id("subs-ended")).to_contain_text("Cancelled in PayPal")
        shot(me, "09_layer2_cancelled")
        step("Priya cancels in (simulated) PayPal -> SubGuard's poll sees CANCELLED -> the band closes")
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
    global SESSION, HTTP
    password = demo_password()  # fails with a clear message when DEMO_PASSWORD isn't in .env
    proc = data = None
    base = args.base_url
    if not base:
        proc, base, data = start_server(password)
    print(f"UI check against {base}")
    try:
        SESSION = session_cookie(base, password)
    except SystemExit:
        if proc is not None:
            proc.terminate()
        raise
    HTTP = http_client(base, SESSION, timeout=30)
    try:
        companion_in_view(base, args.headed)
        story(base, args.headed)
        mobile(base, args.headed)
        autoplay(base, args.headed)
        layer2(base, args.headed)
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

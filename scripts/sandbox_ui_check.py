"""End-to-end check of the REAL PayPal sandbox approval in the demo (D-113). Sandbox only; needs `make seed` first.

Starts a sandbox-mode server on a throwaway DATA_DIR (with your seeded sandbox_ids.json), then drives the shop:
companion -> "Continue to PayPal" -> the real PayPal JS SDK Subscribe button -> PayPal's approval pop-up (logs in
as PAYPAL_SANDBOX_BUYER_EMAIL and consents) -> "Subscribed via PayPal ✓" card (status ACTIVE read live from
PayPal) on the shop and both dashboards -> Cancel on userA's dashboard -> the same card shows CANCELLED from
PayPal + "View in PayPal sandbox" -> opens that link while logged in as the buyer to check it really is the
automatic-payments page. Prints each step; exits non-zero on any failure. Screenshots with --shots DIR.

Usage: python scripts/sandbox_ui_check.py [--headed] [--shots DIR] [--keep-server]
"""

from __future__ import annotations

import argparse
import asyncio
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
from playwright.async_api import Page, async_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sandbox_buyer import _consent, _login, _visible  # noqa: E402

from app.config import Settings  # noqa: E402
from app.integrations.paypal_sdk import SdkPayPal  # noqa: E402

CYCLES = ["10-day trial $0", "3 × $24.99/month", "then $49.99/month"]
errors: list[str] = []


def step(msg: str) -> None:
    print(f"  - {msg}", flush=True)


def llm_key_set() -> bool:
    s = Settings()  # type: ignore[call-arg]
    key = s.anthropic_api_key if s.llm_provider == "anthropic" else s.openai_api_key
    return bool((key or "").strip())


def start_server() -> tuple[subprocess.Popen[bytes], str]:
    ids = ROOT / "data" / "runtime" / "sandbox_ids.json"
    if not ids.exists():
        sys.exit("No data/runtime/sandbox_ids.json: run `make seed` (python scripts/tasks.py seed) first.")
    data = Path(tempfile.mkdtemp(prefix="subguard-sbx-"))
    shutil.copytree(ROOT / "data" / "seed", data / "seed")
    (data / "runtime").mkdir()
    shutil.copy(ids, data / "runtime" / "sandbox_ids.json")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "APP_MODE": "sandbox", "DATA_DIR": str(data), "DEMO_SEED": "true"}
    log = open(data / "server.log", "wb")  # noqa: SIM115 - kept open for the server's lifetime
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    if not llm_key_set():
        # PayPal-only run: the real server refuses to start without an LLM key (CLAUDE.md), and that rule stays.
        # This dev check builds the sandbox app with a placeholder key, so every PayPal call is real while the
        # companion falls back to its labelled "basic check (AI unavailable)" review.
        print("No LLM key in .env: PayPal-only run (companion uses the basic, no-AI review).")
        env["APP_MODE"] = "mock"  # only for importing app.main's module-level app; the served app is sandbox
        launcher = ("import uvicorn; from app.config import Settings; from app.main import create_app; "
                    "s = Settings(app_mode='sandbox', llm_provider='anthropic', "
                    "anthropic_api_key='paypal-only-check'); "
                    f"uvicorn.run(create_app(s), host='127.0.0.1', port={port})")
        cmd = [sys.executable, "-c", launcher]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            if httpx.get(f"{base}/healthz", timeout=2).status_code == 200:
                print(f"sandbox server at {base} (log: {data / 'server.log'})")
                return proc, base
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    sys.exit(f"server didn't start; see {data / 'server.log'}")


def watch(page: Page) -> Page:
    page.on("pageerror", lambda e: errors.append(f"{page.url}: pageerror: {e}"))
    return page


async def card_says(page: Page, scope: str, status: str) -> None:
    card = page.locator(scope).get_by_test_id("paypal-subscribed").first
    await expect(card.get_by_test_id("paypal-status")).to_have_text(status, timeout=60000)
    for text in CYCLES:
        await expect(card.get_by_test_id("paypal-cycles")).to_contain_text(text)
    await expect(card).to_contain_text("fetched live from PayPal")


async def run(base: str, headed: bool, shots: Path | None) -> None:
    s = Settings()  # type: ignore[call-arg]
    email, password = s.paypal_sandbox_buyer_email, s.paypal_sandbox_buyer_password
    if not (email and password):
        sys.exit("Set PAYPAL_SANDBOX_BUYER_EMAIL and PAYPAL_SANDBOX_BUYER_PASSWORD in .env")

    async def shot(page: Page, name: str) -> None:
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(shots / f"{name}.png"), full_page=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 1000})
        shop = watch(await ctx.new_page())
        await shop.goto(f"{base}/shop/penwright?user=usera")
        await shop.get_by_test_id("shop-paypal-btn").click()
        await expect(shop.get_by_test_id("companion-continue")).to_be_visible(timeout=90000)
        risk = shop.get_by_test_id("companion-risk")
        step(f"companion: {await risk.inner_text() if await risk.count() else 'review unavailable (error path)'}")
        await shop.get_by_test_id("companion-continue").click()

        frame = shop.frame_locator("#paypal-area iframe").first
        button = frame.locator("[data-funding-source='paypal']").first
        await expect(button).to_be_visible(timeout=30000)
        step("real PayPal JS SDK Subscribe button rendered for the seeded penwright-pro plan")
        await shot(shop, "s1_paypal_button")

        # PayPal draws the button before its click handler is ready: a click in that gap does nothing (no
        # createSubscription call). A person never clicks that fast, so the check waits a moment and retries.
        await shop.wait_for_timeout(2000)
        pop = None
        for attempt in (1, 2, 3):
            try:
                async with ctx.expect_page(timeout=15000) as pop_info:  # opened from PayPal's iframe, not the page
                    await button.click()
                pop = await pop_info.value
                break
            except Exception:
                status_text = await shop.locator(".checkout-status").all_inner_texts()
                print(f"    attempt {attempt}: no PayPal window yet; checkout status {status_text}")
                if attempt == 3:
                    await shot(shop, "s1_no_popup")
                    raise
                await shop.wait_for_timeout(2000)
        assert pop is not None
        await pop.wait_for_load_state("domcontentloaded")
        step(f"PayPal approval pop-up opened: {pop.url.split('?')[0]}")
        if await _visible(pop, "#email, #password", 20000):
            await _login(pop, email, password)
        await shot(pop, "s2_paypal_popup")
        for attempt in (1, 2, 3):
            try:
                await _consent(pop)
                await pop.wait_for_event("close", timeout=45000)
                break
            except Exception:  # noqa: BLE001 - PayPal's page may need another click after login
                if pop.is_closed():
                    break
                if attempt == 3:
                    await shot(pop, "s2_paypal_popup_stuck")
                    raise
        step("buyer logged in and agreed in PayPal's window; pop-up closed")

        await expect(shop.get_by_test_id("shop-open-subguard")).to_be_visible(timeout=90000)
        await card_says(shop, "[data-testid=shop-paypal-card]", "ACTIVE")
        sub_id_text = await shop.get_by_test_id("paypal-sub-id").first.inner_text()
        step(f"shop: 'Subscribed via PayPal ✓' {sub_id_text} ACTIVE (live), cycles {', '.join(CYCLES)}")
        await shot(shop, "s3_shop_subscribed")

        demo = watch(await ctx.new_page())
        await demo.goto(f"{base}/?demo=1")
        await card_says(demo, "#pp-demo", "ACTIVE")
        me = watch(await ctx.new_page())
        await me.goto(f"{base}/user")
        await card_says(me, "#pp-user", "ACTIVE")
        assert await me.locator("#pp-user").get_by_test_id("paypal-sub-id").inner_text() == sub_id_text
        step("both dashboards show the same card, ACTIVE read live from PayPal")

        await me.get_by_test_id("sub-cancel").click()
        await me.get_by_test_id("confirm-card").get_by_test_id("confirm-button").click()
        await expect(me.get_by_test_id("email-preview")).to_be_visible(timeout=60000)
        await me.get_by_test_id("email-dismiss").click()
        await card_says(me, "#pp-user", "CANCELLED")
        user_card = me.locator("#pp-user").get_by_test_id("paypal-subscribed")
        await expect(user_card).to_contain_text("PayPal-Request-Id")
        link = user_card.get_by_test_id("paypal-autopay-link")
        href = await link.get_attribute("href")
        await shot(me, "s4_user_cancelled")
        step(f"userA cancelled: same {sub_id_text}, CANCELLED read live from PayPal, link {href}")
        await card_says(demo, "#pp-demo", "CANCELLED")
        step("control room card also shows CANCELLED from PayPal")

        auto = await ctx.new_page()  # the buyer's PayPal session from the pop-up is in this context
        await auto.goto(href or "", wait_until="domcontentloaded", timeout=60000)
        if await _visible(auto, "#email, #password", 8000):
            await _login(auto, email, password)
        try:
            await auto.wait_for_url(re.compile(r"/myaccount/autopay"), timeout=60000)
            await auto.wait_for_timeout(5000)  # PayPal's account pages keep polling: no "network idle"
            await shot(auto, "s5_paypal_autopay")
            text = await auto.locator("body").inner_text()
            seen = "Penwright" in text or "SubGuard" in text
            step(f"'View in PayPal sandbox' lands on {auto.url.split('?')[0]} (automatic payments page"
                 f"{', lists the merchant' if seen else ''})")
        except Exception:
            await shot(auto, "s5_paypal_autopay_failed")
            print("    autopay page didn't load as expected; now at", auto.url[:120])
            raise

        audit = httpx.get(f"{base}/api/audit-log?event=paypal_subscription_verified", timeout=10).json()
        real = [e for e in audit if e.get("paypal_debug_id") and not e["paypal_debug_id"].startswith("mock-")]
        assert real, "no live verification with a PayPal debug id in the audit log"
        cancels = httpx.get(f"{base}/api/audit-log?event=paypal_cancel", timeout=10).json()
        step(f"audit: {len(real)} live reads with PayPal debug ids; cancel request id "
             f"{cancels[-1]['paypal_request_id']} via {cancels[-1]['transport']}")
        await browser.close()


async def cleanup(base: str) -> None:
    """Never leave a test subscription ACTIVE in the sandbox: cancel any this run created (asks PayPal, not us)."""
    try:
        subs = httpx.get(f"{base}/api/subscriptions?user=usera", timeout=10).json()
    except httpx.HTTPError:
        return
    sdk = SdkPayPal(Settings(app_mode="sandbox"))  # type: ignore[call-arg]
    try:
        for sub in subs:
            view = await sdk.get_subscription(sub["paypal_id"])
            if view.status in ("ACTIVE", "APPROVED", "SUSPENDED"):
                await sdk.cancel_subscription(sub["paypal_id"], "SubGuard sandbox check cleanup",
                                              request_id=f"subguard-cleanup-{sub['paypal_id']}")
                print(f"  (cleanup: cancelled leftover {sub['paypal_id']} in the sandbox)")
    except Exception as exc:  # noqa: BLE001 - best effort; report it
        print(f"  (cleanup failed: {type(exc).__name__}; check the sandbox for ACTIVE test subscriptions)")
    finally:
        await sdk.aclose()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--shots")
    ap.add_argument("--keep-server", action="store_true")
    args = ap.parse_args()
    proc, base = start_server()
    try:
        asyncio.run(run(base, args.headed, Path(args.shots) if args.shots else None))
    finally:
        asyncio.run(cleanup(base))
        if not args.keep_server:
            proc.terminate()
    if errors:
        print("Page errors:\n  " + "\n  ".join(errors))
        return 1
    print("Sandbox check passed: real PayPal approval and cancel, status read live from PayPal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

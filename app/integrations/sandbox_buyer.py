"""Approve sandbox subscriptions as the sandbox personal buyer, with Playwright (sandbox only).

Used by `make seed --demo-subs`, the sandbox UI check, and the live demo's Start button (D-116), where a visible
browser window logs in and approves so the judges see PayPal's real consent page without anyone typing.

PayPal only lets the buyer approve a subscription, on PayPal's own page. This logs in with
PAYPAL_SANDBOX_BUYER_EMAIL / _PASSWORD and clicks the consent button. Selectors are PayPal's sandbox
checkout as of 2026-11; if they change, run with --headed and look. Sandbox only.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from playwright.async_api import Error as PwError
from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PwTimeout

RETURN_URL = "http://127.0.0.1:8000/shop/sandbox-return"
CANCEL_URL = "http://127.0.0.1:8000/shop/sandbox-cancel"
RETURN_RE = re.compile(r"^http://127\.0\.0\.1:8000/shop/sandbox-return")
CONSENT = re.compile(r"agree|subscribe|continue", re.I)


async def _visible(page: Page, selector: str, timeout: float = 4000) -> bool:
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout)
        return True
    except PwTimeout:
        return False


async def _login(page: Page, email: str, password: str) -> None:
    if await _visible(page, "#email", 15000):
        await page.fill("#email", email)
        if await _visible(page, "#btnNext", 2000):
            await page.click("#btnNext")
    if await _visible(page, "#password", 15000):
        await page.fill("#password", password)
        await page.click("#btnLogin")


SELLER_LOGIN = "account of the seller"


async def _consent(page: Page) -> None:
    if SELLER_LOGIN in (await page.content()):
        raise RuntimeError("PAYPAL_SANDBOX_BUYER_EMAIL is the sandbox BUSINESS (seller) account; PayPal needs a "
                           "separate sandbox PERSONAL account to approve (developer.paypal.com > Sandbox accounts)")
    for selector in ("#consentButton", "button[data-testid='consentButton']", "#confirmButtonTop"):
        if await _visible(page, selector, 20000 if selector == "#consentButton" else 3000):
            await page.locator(selector).first.click()
            return
    await page.get_by_role("button", name=CONSENT).first.click(timeout=10000)


CONSENT_SELECTORS = "#consentButton, button[data-testid='consentButton'], #confirmButtonTop"
CLICK_GAP_S = 4.0  # don't click again while PayPal is still moving to its next page


async def _click_through(page: Page, timeout_s: float = 90) -> None:
    """Click PayPal's consent buttons until it redirects back to us.

    PayPal's sandbox shows one page ("Agree & Subscribe") or two ("Continue", then "Agree & Subscribe"),
    depending on the checkout version. Instead of waiting for one fixed button, look every half second for any
    of them and click the one on screen, so no time is lost on buttons that never appear (D-116).
    """
    loop = asyncio.get_running_loop()
    end, last_click, checked_url = loop.time() + timeout_s, 0.0, ""
    while loop.time() < end:
        if RETURN_RE.match(page.url):
            return
        try:
            if page.url != checked_url:
                checked_url = page.url
                if SELLER_LOGIN in (await page.content()):
                    raise RuntimeError("PAYPAL_SANDBOX_BUYER_EMAIL is the sandbox BUSINESS (seller) account; "
                                       "PayPal needs a separate sandbox PERSONAL account to approve")
            button = page.locator(CONSENT_SELECTORS).or_(page.get_by_role("button", name=CONSENT)).first
            if loop.time() - last_click > CLICK_GAP_S and await button.is_visible() and await button.is_enabled():
                await button.click(timeout=5000)
                last_click = loop.time()
        except PwError:
            pass  # the page navigated mid-check; look again
        await asyncio.sleep(0.5)
    raise PwTimeout(f"PayPal didn't return to SubGuard within {timeout_s:.0f}s (last page: {page.url[:80]})")


async def approve_all(urls: list[str], email: str, password: str, *, headed: bool = True,
                      shots_dir: Path | None = None, slow_mo: float = 0) -> list[bool]:
    """Approve each URL in one browser session. Returns one ok flag per URL (True = reached return URL)."""
    results: list[bool] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed, slow_mo=slow_mo)
        context = await browser.new_context()
        await context.route(re.compile(r"^http://127\.0\.0\.1:8000/shop/sandbox-"),
                            lambda route: route.fulfill(status=200, body="SubGuard sandbox return"))
        page = await context.new_page()
        for i, url in enumerate(urls):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if not page.url.startswith(RETURN_URL):
                    if await _visible(page, "#email, #password", 8000):
                        await _login(page, email, password)
                    await _click_through(page)
                results.append(True)
            except Exception as exc:  # noqa: BLE001 - report and keep going
                print(f"  approve #{i + 1} failed: {type(exc).__name__}: {str(exc)[:160]}")
                if shots_dir:
                    shots_dir.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(shots_dir / f"approve-{i + 1}.png"), full_page=True)
                results.append(False)
        await browser.close()
    return results

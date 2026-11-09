"""Approve sandbox subscriptions as the sandbox personal buyer, with Playwright (dev tooling only).

PayPal only lets the buyer approve a subscription, on PayPal's own page. This logs in with
PAYPAL_SANDBOX_BUYER_EMAIL / _PASSWORD and clicks the consent button. Selectors are PayPal's sandbox
checkout as of 2026-11; if they change, run with --headed and look. Sandbox only.
"""

from __future__ import annotations

import re
from pathlib import Path

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


async def approve_all(urls: list[str], email: str, password: str, *, headed: bool = True,
                      shots_dir: Path | None = None) -> list[bool]:
    """Approve each URL in one browser session. Returns one ok flag per URL (True = reached return URL)."""
    results: list[bool] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
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
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except PwTimeout:
                        pass  # PayPal pages may keep polling; the consent retry below covers it
                    for attempt in (1, 2, 3):  # right after login the first click can land before the page is live
                        await _consent(page)
                        try:
                            await page.wait_for_url(RETURN_RE, timeout=30000)
                            break
                        except PwTimeout:
                            if attempt == 3:
                                raise
                results.append(True)
            except Exception as exc:  # noqa: BLE001 - report and keep going
                print(f"  approve #{i + 1} failed: {type(exc).__name__}: {str(exc)[:160]}")
                if shots_dir:
                    shots_dir.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(shots_dir / f"approve-{i + 1}.png"), full_page=True)
                results.append(False)
        await browser.close()
    return results

"""Live page capture with Playwright (sandbox mode): computed styles, hidden state, screenshot, bounding boxes.
Falls back to the static capture (with a logged warning) if the browser can't run."""

from __future__ import annotations

import base64
import logging
from typing import Any

from app.integrations.capture import (
    CaptureError,
    Checkbox,
    PageCapture,
    StaticCapture,
    TextBlock,
    _merchant_from_path,
    _terms_links,
    contrast_ratio,
    normalize_ws,
)

log = logging.getLogger("subguard.capture")

CAPTURE_JS = r"""
() => {
  const BLOCK = new Set(["P","H1","H2","H3","H4","LI","DIV","SUMMARY","LABEL","A","BUTTON","SPAN","HEADER",
                         "SECTION","ARTICLE","TD","TH","MAIN","BODY"]);
  const hiddenReason = (el) => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === "none") return "display:none";
      if (cs.visibility === "hidden") return "visibility:hidden";
      const d = n.parentElement;
      if (d && d.tagName === "DETAILS" && !d.open && n.tagName !== "SUMMARY") return "collapsed";
    }
    return null;
  };
  const ignored = (el) => !!el.closest("[data-subguard-ignore]");
  const out = {blocks: [], checkboxes: [], links: []};
  for (const el of document.body.querySelectorAll("*")) {
    if (!BLOCK.has(el.tagName) || ignored(el)) continue;
    let text = "";
    const walk = (node) => {
      for (const c of node.childNodes) {
        if (c.nodeType === 3) text += c.textContent + " ";
        else if (c.nodeType === 1 && !BLOCK.has(c.tagName) && !["SCRIPT","STYLE"].includes(c.tagName)) walk(c);
      }
    };
    walk(el);
    text = text.replace(/\s+/g, " ").trim();
    if (!text) continue;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const tid = el.closest("[data-testid]");
    out.blocks.push({text, testid: tid ? tid.dataset.testid : null, hidden_reason: hiddenReason(el),
      font_px: parseFloat(cs.fontSize), color: cs.color,
      bbox: [r.x + scrollX, r.y + scrollY, r.width, r.height]});
  }
  for (const cb of document.querySelectorAll("input[type=checkbox]")) {
    if (ignored(cb)) continue;
    out.checkboxes.push({name: cb.name || "", value: cb.value || "", testid: cb.dataset.testid || null,
                         checked: cb.defaultChecked});
  }
  for (const a of document.querySelectorAll("a[href]")) {
    out.links.push({href: a.getAttribute("href"), text: a.textContent.trim()});
  }
  return out;
}
"""


class PlaywrightCapture:
    """Live Chromium capture (sandbox mode). Falls back to the static capture if the browser can't run."""

    method = "playwright"

    def __init__(self, fallback: StaticCapture, timeout_ms: int = 15000) -> None:
        self.fallback = fallback
        self.timeout_ms = timeout_ms

    async def _page(self, browser: Any, url: str, page_path: str, shot: bool) -> tuple[dict[str, Any], str | None]:
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            await page.goto(url, wait_until="load", timeout=self.timeout_ms)
            png = await page.screenshot(full_page=True) if shot else None
            data = await page.evaluate(CAPTURE_JS)
        finally:
            await page.close()
        return data, base64.b64encode(png).decode() if png else None

    def _to_capture(self, data: dict[str, Any], page: str, cap: PageCapture) -> list[tuple[str, str]]:
        for b in data.get("blocks", []):
            cap.blocks.append(TextBlock(page=page, text=normalize_ws(b["text"]), testid=b.get("testid"),
                                        hidden=bool(b.get("hidden_reason")), hidden_reason=b.get("hidden_reason"),
                                        font_px=float(b.get("font_px", 16)), color=b.get("color", "#222"),
                                        contrast=contrast_ratio(b.get("color", "#222")), bbox=b.get("bbox")))
        for c in data.get("checkboxes", []):
            cap.checkboxes.append(Checkbox(page=page, **c))
        return [(lk["href"], lk["text"]) for lk in data.get("links", [])]

    async def capture(self, path: str, base_url: str) -> PageCapture:
        merchant = _merchant_from_path(path)
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as pw:
                browser = await pw.chromium.launch()
                try:
                    data, png = await self._page(browser, base_url.rstrip("/") + path, path, shot=True)
                    cap = PageCapture(url=path, merchant_id=merchant, screenshot_png_b64=png, method=self.method)
                    links = self._to_capture(data, path, cap)
                    for link in _terms_links(links, path):
                        sub, _ = await self._page(browser, base_url.rstrip("/") + link, link, shot=False)
                        self._to_capture(sub, link, cap)
                        cap.linked_pages.append(link)
                finally:
                    await browser.close()
            return cap
        except CaptureError:
            raise
        except Exception as exc:  # browser missing / crashed -> static capture, logged
            log.warning(f"live capture failed, using static capture: {type(exc).__name__}: {str(exc)[:160]}")
            return await self.fallback.capture(path, base_url)

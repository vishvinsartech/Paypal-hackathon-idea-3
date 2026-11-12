"""Page capture (spec 7.2 step 1): text blocks with style signals, hidden text, checkbox defaults, linked ToS.

Two implementations behind one interface (D-040):
- `StaticCapture` (mock mode, and the fallback): fetches our own shop pages through the ASGI app and parses the
  HTML + shop.css. Deterministic, no browser, works on hosted Render.
- `PlaywrightCapture` (sandbox mode, capture_live.py): live Chromium; adds a screenshot and bounding boxes.
Only same-site `/shop/...` pages are captured (never arbitrary URLs).
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

log = logging.getLogger("subguard.capture")
SHOP_PATH_RE = re.compile(r"^/shop/[a-z0-9-]+(/terms)?$")
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "div", "summary", "label", "a", "button", "span", "header",
              "section", "article", "td", "th", "main"}
SKIP_TAGS = {"script", "style", "head", "title", "noscript", "template"}
VOID_TAGS = {"input", "br", "img", "meta", "link", "hr"}
DEFAULT_FONT = {"h1": 32.0, "h2": 24.0, "h3": 18.7, "h4": 16.0, "small": 13.3}


class CaptureError(RuntimeError):
    pass


class TextBlock(BaseModel):
    page: str
    text: str
    testid: str | None = None
    hidden: bool = False
    hidden_reason: str | None = None  # display:none | visibility:hidden | collapsed
    font_px: float = 16.0
    color: str = "#222222"
    contrast: float = 21.0
    bbox: list[float] | None = None  # x, y, w, h (live capture only)


class Checkbox(BaseModel):
    page: str
    name: str = ""
    value: str = ""
    testid: str | None = None
    checked: bool = False


class PageCapture(BaseModel):
    url: str
    merchant_id: str
    blocks: list[TextBlock] = Field(default_factory=list)
    checkboxes: list[Checkbox] = Field(default_factory=list)
    linked_pages: list[str] = Field(default_factory=list)
    screenshot_png_b64: str | None = None
    method: str = "static"

    @property
    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)

    def main_blocks(self) -> list[TextBlock]:
        return [b for b in self.blocks if b.page == self.url]

    def for_llm(self) -> str:
        """Text + style signals, one block per line. Clearly delimited as untrusted page data."""
        lines = []
        for b in self.blocks:
            tags = [f"page={b.page}", f"testid={b.testid or '-'}", f"font={b.font_px:.0f}px",
                    f"contrast={b.contrast:.1f}:1"]
            if b.hidden:
                tags.append(f"HIDDEN({b.hidden_reason})")
            lines.append(f"[{' | '.join(tags)}] {b.text}")
        for c in self.checkboxes:
            lines.append(f"[checkbox testid={c.testid or '-'} value={c.value} default_checked={c.checked}]")
        return "\n".join(lines)


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---- colour maths (WCAG) -----------------------------------------------------
def _hex_rgb(color: str) -> tuple[int, int, int] | None:
    c = color.strip().lower()
    if m := re.fullmatch(r"#([0-9a-f]{3})", c):
        return tuple(int(ch * 2, 16) for ch in m.group(1))  # type: ignore[return-value]
    if m := re.fullmatch(r"#([0-9a-f]{6})", c):
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if m := re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+).*\)", c):
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def contrast_ratio(fg: str, bg: str = "#ffffff") -> float:
    def lum(rgb: tuple[int, int, int]) -> float:
        def ch(v: int) -> float:
            s = v / 255
            return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
        r, g, b = rgb
        return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)
    a, b = _hex_rgb(fg), _hex_rgb(bg)
    if a is None or b is None:
        return 21.0
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return round((hi + 0.05) / (lo + 0.05), 2)


# ---- static capture -----------------------------------------------------------
def _parse_css(css: str) -> dict[str, dict[str, str]]:
    """Single-class rules only (`.fineprint { font-size: 9px; color: #9a9a9a }`), enough for our shop."""
    rules: dict[str, dict[str, str]] = {}
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        decls = dict((k.strip().lower(), v.strip()) for k, v in
                     (d.split(":", 1) for d in body.split(";") if ":" in d))
        for one in sel.split(","):
            one = one.strip()
            if re.fullmatch(r"\.[\w-]+", one):
                rules.setdefault(one[1:], {}).update(decls)
    return rules


def _px(value: str, parent: float) -> float | None:
    if m := re.match(r"([\d.]+)px", value):
        return float(m.group(1))
    if m := re.match(r"([\d.]+)rem", value):
        return float(m.group(1)) * 16
    if m := re.match(r"([\d.]+)em", value):
        return float(m.group(1)) * parent
    return None


class _Frame:
    def __init__(self, tag: str, attrs: dict[str, str], parent: _Frame | None, css: dict[str, dict[str, str]]):
        self.tag = tag
        self.parent = parent
        self.testid = attrs.get("data-testid") or (parent.testid if parent else None)
        self.ignore = "data-subguard-ignore" in attrs or bool(parent and parent.ignore)
        style = {k.strip().lower(): v.strip() for k, v in
                 (d.split(":", 1) for d in attrs.get("style", "").split(";") if ":" in d)}
        decls: dict[str, str] = {}
        for cls in attrs.get("class", "").split():
            decls.update(css.get(cls, {}))
        decls.update(style)
        if "font-size" not in decls and (m := re.search(r"([\d.]+(px|rem|em))", decls.get("font", ""))):
            decls["font-size"] = m.group(1)
        pf = parent.font if parent else 16.0
        self.font = _px(decls.get("font-size", ""), pf) or DEFAULT_FONT.get(tag) or pf
        self.color = decls.get("color") or (parent.color if parent else "#222222")
        self.hidden_reason = parent.hidden_reason if parent else None
        if decls.get("display", "").startswith("none"):
            self.hidden_reason = "display:none"
        elif decls.get("visibility", "").startswith("hidden"):
            self.hidden_reason = "visibility:hidden"
        elif parent and parent.tag == "details" and not parent.open and tag != "summary" and not self.hidden_reason:
            self.hidden_reason = "collapsed"
        self.open = "open" in attrs
        self.text: list[str] = []


class _ShopParser(HTMLParser):
    def __init__(self, page: str, css: dict[str, dict[str, str]]) -> None:
        super().__init__(convert_charrefs=True)
        self.page, self.css = page, css
        self.stack: list[_Frame] = []
        self.blocks: list[TextBlock] = []
        self.checkboxes: list[Checkbox] = []
        self.links: list[tuple[str, str]] = []  # href, text
        self._skip = 0
        self._link: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        parent = self.stack[-1] if self.stack else None
        if tag == "input":
            if attrs.get("type") == "checkbox" and not (parent and parent.ignore):
                self.checkboxes.append(Checkbox(page=self.page, name=attrs.get("name", ""),
                                                value=attrs.get("value", ""), testid=attrs.get("data-testid"),
                                                checked="checked" in attrs))
            return
        if tag in VOID_TAGS:
            return
        if tag == "a":
            self._link = (attrs.get("href", ""), [])
        self.stack.append(_Frame(tag, attrs, parent, self.css))

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in VOID_TAGS or not any(f.tag == tag for f in self.stack):
            return
        while self.stack:
            frame = self.stack.pop()
            self._flush(frame)
            if frame.tag == tag:
                break
        if tag == "a" and self._link:
            self.links.append((self._link[0], normalize_ws(" ".join(self._link[1]))))
            self._link = None

    def handle_data(self, data: str) -> None:
        if self._skip or not self.stack:
            return
        target = next((f for f in reversed(self.stack) if f.tag in BLOCK_TAGS or f.tag in ("details", "body")),
                      self.stack[-1])
        target.text.append(data)
        if self._link:
            self._link[1].append(data)

    def _flush(self, frame: _Frame) -> None:
        text = normalize_ws(" ".join(frame.text))
        if not text or frame.ignore:
            return
        self.blocks.append(TextBlock(
            page=self.page, text=text, testid=frame.testid, hidden=frame.hidden_reason is not None,
            hidden_reason=frame.hidden_reason, font_px=round(frame.font, 1), color=frame.color,
            contrast=contrast_ratio(frame.color)))


def _merchant_from_path(path: str) -> str:
    if not SHOP_PATH_RE.match(path):
        raise CaptureError(f"Only SubGuard demo shop pages can be reviewed, not {path!r}")
    return path.split("/")[2]


def _terms_links(links: list[tuple[str, str]], path: str) -> list[str]:
    merchant = path.split("/")[2]
    out = []
    for href, text in links:
        if ("terms" in href.lower() or "terms" in text.lower()) and href.startswith(f"/shop/{merchant}/"):
            if SHOP_PATH_RE.match(href) and href != path and href not in out:
                out.append(href)
    return out[:1]  # one level, one page


class Capturer(Protocol):
    method: str

    async def capture(self, path: str, base_url: str) -> PageCapture: ...


class StaticCapture:
    method = "static"

    def __init__(self, app: Any, css_path: Path) -> None:
        self.app = app
        self.css_path = css_path

    async def _fetch(self, client: httpx.AsyncClient, path: str) -> str:
        res = await client.get(path)
        if res.status_code != 200:
            raise CaptureError(f"{path} returned HTTP {res.status_code}")
        return res.text

    def parse(self, html: str, page: str) -> _ShopParser:
        parser = _ShopParser(page, _parse_css(self.css_path.read_text(encoding="utf-8")))
        parser.feed(html)
        parser.close()
        while parser.stack:
            parser._flush(parser.stack.pop())
        return parser

    async def capture(self, path: str, base_url: str = "http://shop.local") -> PageCapture:
        merchant = _merchant_from_path(path)
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://shop.local") as client:
            main = self.parse(await self._fetch(client, path), path)
            cap = PageCapture(url=path, merchant_id=merchant, blocks=main.blocks, checkboxes=main.checkboxes,
                              method=self.method)
            for link in _terms_links(main.links, path):
                sub = self.parse(await self._fetch(client, link), link)
                cap.blocks += sub.blocks
                cap.checkboxes += sub.checkboxes
                cap.linked_pages.append(link)
        return cap

"""Phase 7 Step 3 (D-182): the avatar menu, Settings' account cards, Last signed in, and the demo-only controls."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import ROOT_DIR, Settings
from app.routes.account_view import last_signed_in, short_email

SUCCESS = re.compile(r"\b(saved|updated|changed|enabled|turned on|deleted|added|done|success)\b", re.I)


class _Soon(HTMLParser):
    """Every element with data-soon: its tag, attributes and text."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[dict] = []
        self._open: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if "data-soon" in a:
            item = {"tag": tag, "attrs": a, "text": ""}
            self.found.append(item)
            self._open.append(item)

    def handle_endtag(self, tag: str) -> None:
        if self._open and self._open[-1]["tag"] == tag:
            self._open.pop()

    def handle_data(self, data: str) -> None:
        for item in self._open:
            item["text"] += data


def _soon(html: str) -> list[dict]:
    p = _Soon()
    p.feed(html)
    return p.found


def test_data_soon_controls_are_buttons_or_links_with_no_success_wording(client: TestClient) -> None:
    html = client.get("/").text
    found = _soon(html)
    ids = {f["attrs"].get("data-testid") for f in found}
    assert ids == {"subs-add", "profile-edit", "sec-password", "sec-2fa", "delete-account",
                   "footer-help", "footer-privacy"}
    for f in found:
        assert f["tag"] in ("button", "a"), f
        assert not SUCCESS.search(f["text"]), f
    delete = next(f for f in found if f["attrs"].get("data-testid") == "delete-account")
    assert "disabled" in delete["attrs"] and delete["text"].strip() == "Demo account"
    assert "SubGuard adds subscriptions you start with PayPal" in html
    # the one handler: the toast says it's not part of the demo, and makes no request
    js = (ROOT_DIR / "app" / "static" / "user-nav.js").read_text(encoding="utf-8")
    handler = js[js.index('closest("[data-soon]")'):js.index("const nav =")]
    assert '"Not part of this demo"' in handler
    assert "api(" not in handler and "fetch(" not in handler and not SUCCESS.search(handler)


def test_signed_out_pages_have_the_footer_soon_links(anon_client: TestClient) -> None:
    for path in ("/", "/login"):
        html = anon_client.get(path).text
        assert {f["attrs"].get("data-testid") for f in _soon(html)} == {"footer-help", "footer-privacy"}
        assert "/static/user-nav.js" in html


def test_avatar_menu(client: TestClient) -> None:
    html = client.get("/").text
    assert re.search(r"Signed in as Priya<span class=\"menu-email\"> · priya@…</span>", html)
    assert "@subguard-demo.example" not in html.split('data-testid="avatar-signed-in"')[1].split("</p>")[0]
    for testid in ("avatar-profile", "avatar-settings", "avatar-emails", "avatar-help", "avatar-signout"):
        assert f'data-testid="{testid}"' in html, testid
    assert re.search(r'<form method="post" action="/logout"[^>]*><button type="submit"[^>]*avatar-signout', html)
    assert 'data-testid="topnav-presenter"' in html


def test_connected_accounts_mock(client: TestClient, settings: Settings) -> None:
    html = client.get("/").text
    card = html.split('data-testid="connected-accounts"')[1].split("</section>")[0]
    assert "Demo data" in card and ">Connected<" in card and ">Mocked<" in card
    assert "PayPal Sandbox" not in card
    for secret in (settings.demo_password, "hooks.zapier.com"):
        assert secret and secret not in html
    assert 'href="/api/audit-log.csv?user=priya"' in html
    res = client.get("/api/audit-log.csv?user=priya")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")


def test_last_signed_in(client: TestClient) -> None:
    html = client.get("/").text
    assert re.search(r'data-testid="side-last-signin">Last signed in [A-Z][a-z]{2} \d{1,2}, \d\d:\d\d UTC<', html)


def test_last_signed_in_hidden_without_an_entry(client: TestClient, data_dir: Path) -> None:
    store = client.app.state.store  # type: ignore[attr-defined]
    assert last_signed_in(store, "nobody") is None
    assert short_email("priya@subguard-demo.example") == "priya@…" and short_email("") == ""

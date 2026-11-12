"""Sign in to a running SubGuard as Priya (Phase 7, D-178): for ui_check.py and the demo-video tools.

The password comes from DEMO_PASSWORD (environment first, then .env); nothing is hardcoded (D-180).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
COOKIE = "sg_session"


def demo_password() -> str:
    password = os.environ.get("DEMO_PASSWORD") or dotenv_values(ROOT / ".env").get("DEMO_PASSWORD") or ""
    if not password:
        raise SystemExit("DEMO_PASSWORD is missing: SubGuard pages need sign-in now. Set DEMO_PASSWORD in .env "
                         "(see .env.example) to the password the app uses, then run this again.")
    return password


def priya_email() -> str:
    users = json.loads((ROOT / "data" / "seed" / "users.json").read_text(encoding="utf-8"))["items"]
    return next(u["email"] for u in users if u["id"] == "priya")


def session_cookie(base: str, password: str | None = None) -> str:
    """POST /login like the form does and return the sg_session cookie value."""
    res = httpx.post(base.rstrip("/") + "/login", follow_redirects=False, timeout=15,
                     data={"email": priya_email(), "password": password or demo_password(), "next": "/"})
    value = res.cookies.get(COOKIE)
    if res.status_code != 303 or not value:
        raise SystemExit(f"Sign-in failed at {base} (HTTP {res.status_code}). Is DEMO_PASSWORD in .env the one "
                         "the running app uses?")
    return value


def http_client(base: str, cookie: str, **kw: Any) -> httpx.Client:
    """An httpx client that sends Priya's session cookie."""
    return httpx.Client(base_url=base.rstrip("/"), cookies={COOKIE: cookie}, **kw)


def add_session(ctx: Any, base: str, cookie: str) -> Any:
    """Give a Playwright browser context Priya's session (sync or async API: add_cookies returns what it returns)."""
    return ctx.add_cookies([{"name": COOKIE, "value": cookie, "url": base.rstrip("/") + "/", "httpOnly": True,
                             "sameSite": "Lax"}])

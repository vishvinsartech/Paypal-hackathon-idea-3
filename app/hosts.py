"""Where the app is running: a local machine or a hosted one (Render). D-183."""

from __future__ import annotations

import importlib.util
import os
import sys

from starlette.requests import Request

from app.config import Settings

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_local(request: Request) -> bool:
    """True when the browser reached us on this machine (the sandbox buyer window only works there)."""
    return (request.url.hostname or "") in LOCAL_HOSTS


def is_hosted() -> bool:
    """Render sets RENDER in every service's environment; that means no screen and no local return URL."""
    return bool(os.environ.get("RENDER", "").strip())


def browser_available() -> bool:
    """Playwright is installed and, on Linux, there is a display for the headed PayPal window."""
    if importlib.util.find_spec("playwright") is None:
        return False
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def can_auto_approve(settings: Settings, request: Request | None = None) -> bool:
    """D-192: True only when the server-side logged-in PayPal window (sandbox_buyer.py) can really run.

    AUTO_APPROVE_MODE=manual|off forces the manual flow; auto (default) detects: not on Render, reached on this
    machine (the window returns to a local URL), and a browser can open.
    """
    if settings.auto_approve_mode != "auto":
        return False
    if is_hosted() or (request is not None and not is_local(request)):
        return False
    return browser_available()


def show_sandbox_buyer(settings: Settings) -> bool:
    """D-192: the hosted Penwright window may print the sandbox buyer's login (play money only)."""
    return (settings.is_sandbox and settings.show_sandbox_buyer and settings.auto_approve_mode != "off"
            and bool(settings.paypal_sandbox_buyer_email and settings.paypal_sandbox_buyer_password))


def server_url(settings: Settings) -> str:
    """The URL to print at startup: Render's public URL if set, else the host and the real port ($PORT first)."""
    external = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if external:
        return external + "/"
    port = os.environ.get("PORT", "").strip() or str(settings.app_port)
    return f"http://{settings.app_host}:{port}/"

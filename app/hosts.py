"""Where the app is running: a local machine or a hosted one (Render). D-183."""

from __future__ import annotations

import os

from starlette.requests import Request

from app.config import Settings

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_local(request: Request) -> bool:
    """True when the browser reached us on this machine (the sandbox buyer window only works there)."""
    return (request.url.hostname or "") in LOCAL_HOSTS


def server_url(settings: Settings) -> str:
    """The URL to print at startup: Render's public URL if set, else the host and the real port ($PORT first)."""
    external = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if external:
        return external + "/"
    port = os.environ.get("PORT", "").strip() or str(settings.app_port)
    return f"http://{settings.app_host}:{port}/"

"""Sign-in core (Phase 7 Step 1, D-178..D-180): the signed `sg_session` cookie, the credential check, the sign-in
rate limiter and the access middleware.

Nothing is stored on the server (D-178): the cookie carries `user_id|expiry` and an HMAC-SHA256 signature made with
`SESSION_SECRET`, so a session survives a restart or Render's disk wipe as long as the secret stays the same.
The middleware decides who may reach a route (D-179); R5's `owner_id == user` filters stay the data guard.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from collections import deque
from collections.abc import Iterable
from urllib.parse import parse_qs, quote, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.models import User

COOKIE = "sg_session"
RULE = "AUTH"  # rule id on the sign-in and access audit entries
FAIL_LIMIT = 5  # failed sign-ins per IP ...
FAIL_WINDOW = 60.0  # ... per this many seconds

# D-179: everything else needs a session. Step 2 adds "/" (the intro when signed out); for now it redirects.
PUBLIC_EXACT = frozenset({
    "/login", "/logout", "/healthz",
    "/api/review/preflight",  # the shop companion's read-only check
    "/webhooks/paypal", "/demo/paypal-autopay",
    "/shop",
})
PUBLIC_PREFIXES = ("/static/", "/shop/")  # covers /shop/static/* and the /shop/* pages


# ---- cookie -------------------------------------------------------------------------------------------------
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sig(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())


def sign_session(user_id: str, secret: str, hours: int, now: float | None = None) -> str:
    """`base64(user_id|expiry).base64(HMAC-SHA256)`; expiry is a Unix timestamp."""
    expiry = int((time.time() if now is None else now) + hours * 3600)
    payload = _b64(f"{user_id}|{expiry}".encode())
    return f"{payload}.{_sig(secret, payload)}"


def verify_session(value: str | None, secret: str, now: float | None = None) -> str | None:
    """The user id from a valid, unexpired cookie; None for anything tampered, expired or malformed."""
    if not value or not secret or value.count(".") != 1:
        return None
    payload, sig = value.split(".")
    if not hmac.compare_digest(sig, _sig(secret, payload)):
        return None
    try:
        user_id, expiry = _unb64(payload).decode("utf-8").rsplit("|", 1)
        if not user_id or int(expiry) <= (time.time() if now is None else now):
            return None
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    return user_id


def set_session_cookie(response: Response, request: Request, user_id: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE, sign_session(user_id, settings.session_secret, settings.session_hours),
        max_age=settings.session_hours * 3600, path="/", httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=request.url.scheme == "https")


def session_user(request: Request, settings: Settings) -> str | None:
    return verify_session(request.cookies.get(COOKIE), settings.session_secret)


# ---- credentials ------------------------------------------------------------------------------------------------
def check_credentials(users: Iterable[User], settings: Settings, email: str, password: str) -> str | None:
    """The user id when the email (any case) is in users.json and the password matches DEMO_PASSWORD (D-180).

    Both comparisons always run, so a wrong email and a wrong password take the same path."""
    wanted = email.strip().casefold()
    match = next((u for u in users if u.email and u.email.casefold() == wanted), None)
    expected = settings.demo_password
    ok_password = bool(expected) and hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))
    return match.id if match is not None and ok_password else None


class LoginLimiter:
    """In-memory: at most FAIL_LIMIT failed sign-ins per IP in FAIL_WINDOW seconds (one process, D-020)."""

    def __init__(self, limit: int = FAIL_LIMIT, window: float = FAIL_WINDOW) -> None:
        self.limit, self.window = limit, window
        self._fails: dict[str, deque[float]] = {}

    def _recent(self, ip: str, now: float) -> deque[float]:
        q = self._fails.setdefault(ip, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def blocked(self, ip: str, now: float | None = None) -> bool:
        return len(self._recent(ip, time.monotonic() if now is None else now)) >= self.limit

    def fail(self, ip: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._recent(ip, now).append(now)

    def clear(self, ip: str) -> None:
        self._fails.pop(ip, None)


def safe_next(target: str | None) -> str:
    """A local path ("/..." but not "//..." or "/\\...", no scheme or host); anything else becomes "/"."""
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return "/"
    if any(ord(ch) < 32 for ch in target) or "\\" in target:
        return "/"
    parts = urlsplit(target)
    return target if not parts.scheme and not parts.netloc else "/"


def is_public(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


# ---- middleware -------------------------------------------------------------------------------------------------
class AuthMiddleware:
    """Sets `request.state.user_id` (None when signed out) and guards every non-public route (D-179).

    Signed out: HTML -> 303 to /login?next=..., /api/* -> 401 JSON. Signed in: a `?user=` that isn't the session
    user -> 403. Route signatures and R5 filters don't change."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        settings: Settings = scope["app"].state.settings
        user_id = session_user(request, settings)
        scope.setdefault("state", {})["user_id"] = user_id
        response = self._decide(request, user_id)
        if response is None:
            await self.app(scope, receive, send)
        else:
            await response(scope, receive, send)

    @staticmethod
    def _decide(request: Request, user_id: str | None) -> Response | None:
        path = request.url.path
        is_api = path.startswith("/api/")
        if user_id is None:
            if is_public(path):
                return None
            if is_api:
                return JSONResponse({"detail": "Sign in first.", "rule_id": RULE}, status_code=401)
            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
        asked = parse_qs(request.url.query).get("user", [])
        if any(u != user_id for u in asked):
            audit_access_blocked(request, user_id, asked)
            if is_api:
                return JSONResponse({"detail": "That isn't your account.", "rule_id": RULE}, status_code=403)
            return HTMLResponse("<!doctype html><title>Not your account</title><p>That isn't your account. "
                                '<a href="/">Back to your SubGuard</a></p>', status_code=403)
        return None


def audit_access_blocked(request: Request, user_id: str, asked: list[str]) -> None:
    request.app.state.store.audit.append(
        actor="user", event="access_blocked", user_id=user_id, rule_id=RULE, decision="blocked",
        reason="?user= differs from the signed-in user",
        details={"path": request.url.path, "asked_user": asked},
    )

"""Sign-in routes (Phase 7 Step 1): GET/POST /login and POST /logout. The cookie and checks live in app/auth.py."""

from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.auth import (
    RULE,
    check_credentials,
    clear_session_cookie,
    safe_after_login,
    session_user,
    set_session_cookie,
)
from app.config import Settings
from app.core.audit_log import mask_email
from app.routes.deps import get_settings, get_store
from app.routes.pages import templates
from app.store import JsonStore

router = APIRouter()
WRONG = "Email or password is wrong"
OFF = "Sign-in is off: set DEMO_PASSWORD in .env"
SLOW_DOWN = "Too many tries. Wait a minute and try again."


def _page(request: Request, settings: Settings, nxt: str, error: str | None = None, email: str = "",
          status_code: int = 200) -> HTMLResponse:
    off = not settings.demo_password
    return templates.TemplateResponse(request, "login.html", {
        "next": nxt, "error": OFF if off else error, "email": email, "sign_in_off": off,
    }, status_code=status_code)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request, next: str = "/", settings: Settings = Depends(get_settings)) -> Response:
    nxt = safe_after_login(next)
    if session_user(request, settings):
        return RedirectResponse(nxt, status_code=303)
    return _page(request, settings, nxt)


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login(request: Request, settings: Settings = Depends(get_settings),
                store: JsonStore = Depends(get_store)) -> Response:
    form = parse_qs((await request.body()).decode("utf-8", "replace"))  # stdlib: no python-multipart needed
    email = form.get("email", [""])[0].strip()
    password = form.get("password", [""])[0]
    nxt = safe_after_login(form.get("next", ["/"])[0])
    if not settings.demo_password:
        return _page(request, settings, nxt, email=email, status_code=503)
    limiter = request.app.state.login_limiter
    ip = _ip(request)

    def failed(reason: str) -> None:  # never the password; the email masked (secrets rule)
        store.audit.append(actor="user", event="sign_in_failed", rule_id=RULE, decision="blocked", reason=reason,
                           details={"email": mask_email(email.casefold())})

    if limiter.blocked(ip):
        failed("rate limit: too many failed sign-ins from this address")
        return _page(request, settings, nxt, SLOW_DOWN, email, status_code=429)
    user_id = check_credentials(store.load("users").items, settings, email, password)
    if user_id is None:
        limiter.fail(ip)
        failed("email or password is wrong")
        return _page(request, settings, nxt, WRONG, email, status_code=401)
    limiter.clear(ip)
    store.audit.append(actor="user", event="signed_in", user_id=user_id, rule_id=RULE, decision="allowed",
                       reason="signed in with email and password", details={"email": mask_email(email.casefold())})
    response = RedirectResponse(nxt, status_code=303)
    set_session_cookie(response, request, user_id, settings)
    return response


@router.post("/logout", response_model=None)
def logout(request: Request, settings: Settings = Depends(get_settings),
           store: JsonStore = Depends(get_store)) -> Response:
    user_id = session_user(request, settings)
    if user_id:
        store.audit.append(actor="user", event="signed_out", user_id=user_id, rule_id=RULE, decision="allowed",
                           reason="signed out")
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response, request)
    return response

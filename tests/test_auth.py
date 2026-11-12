"""Sign-in wall (Phase 7, D-178..D-181): login, cookies, redirects, the access middleware, audit, startup rules."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.auth as auth
from app.auth import COOKIE, _b64, _unb64, safe_after_login, safe_next, sign_session, verify_session
from app.config import Settings
from app.main import create_app
from tests.story_helpers import PRIYA_EMAIL, TEST_PASSWORD, audit

EVIL_NEXT = ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)"]


def login(c: TestClient, password: str = TEST_PASSWORD, email: str = PRIYA_EMAIL, nxt: str = "/"):  # noqa: ANN201
    return c.post("/login", data={"email": email, "password": password, "next": nxt}, follow_redirects=False)


def signed_out(c: TestClient) -> bool:
    return c.get("/api/subscriptions").status_code == 401


# ---- sign in -----------------------------------------------------------------------------------------------------
def test_sign_in_sets_a_signed_cookie(anon_client: TestClient, settings: Settings) -> None:
    c = anon_client
    res = login(c, email=PRIYA_EMAIL.upper())  # email compared case-insensitively
    assert res.status_code == 303 and res.headers["location"] == "/"
    cookie = res.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie  # http here; Secure only over https
    assert verify_session(res.cookies[COOKIE], settings.session_secret) == "priya"
    assert c.get("/api/subscriptions").status_code == 200
    assert 'data-testid="hi-name"' in c.get("/").text  # "/" is her dashboard now, not the intro


def test_wrong_password_gets_the_generic_error(anon_client: TestClient) -> None:
    res = login(anon_client, password="nope")
    assert res.status_code == 401 and "Email or password is wrong" in res.text and COOKIE not in res.cookies
    other = login(anon_client, email="who@else.example")  # unknown email: the same message
    assert other.status_code == 401 and "Email or password is wrong" in other.text
    assert signed_out(anon_client)


def test_sixth_failure_within_a_minute_is_rate_limited(anon_client: TestClient,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(auth, "time", SimpleNamespace(time=time.time, monotonic=lambda: clock[0]))
    for i in range(5):
        clock[0] += 10  # 5 failures in 50 s
        assert login(anon_client, password=f"nope{i}").status_code == 401
    clock[0] += 5
    res = login(anon_client, password="nope5")  # the 6th try within the minute
    assert res.status_code == 429 and "Too many tries" in res.text
    res = login(anon_client)  # even the right password waits
    assert res.status_code == 429 and COOKIE not in res.cookies
    clock[0] += 61  # a minute after the failures: allowed again
    assert login(anon_client).status_code == 303
    assert audit(anon_client, "sign_in_failed")[-1]["reason"].startswith("rate limit")


# ---- cookies -----------------------------------------------------------------------------------------------------
def test_tampered_expired_or_wrongly_signed_cookie_is_rejected(anon_client: TestClient, settings: Settings) -> None:
    secret = settings.session_secret
    good = sign_session("priya", secret, 8)
    payload, sig = good.split(".")
    far = int(time.time()) + 10**6
    tampered = _b64(f"intruder|{far}".encode()) + "." + sig  # new payload, old signature
    longer = _b64(_unb64(payload).decode().replace("|", "|9").encode()) + "." + sig  # a later expiry
    bad_cookies = {
        "tampered payload": tampered, "tampered expiry": longer,
        "expired": sign_session("priya", secret, 1, now=time.time() - 7200),
        "wrong signature": sign_session("priya", "another-secret-" * 3, 8),
        "garbage": "not-a-cookie", "two dots": good + ".x",
    }
    for name, value in bad_cookies.items():
        assert verify_session(value, secret) is None, name
        anon_client.cookies.set(COOKIE, value)
        assert signed_out(anon_client), name
        assert anon_client.get("/?demo=1", follow_redirects=False).status_code == 303, name
    anon_client.cookies.set(COOKIE, good)
    assert anon_client.get("/api/subscriptions").status_code == 200


# ---- redirects ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("target,expected", [
    ("/?demo=1", "/?demo=1"), ("/subscriptions/a", "/subscriptions/a"), *[(e, "/") for e in EVIL_NEXT],
    ("", "/"), (None, "/"),
])
def test_next_must_be_a_local_path(target: str | None, expected: str) -> None:
    assert safe_next(target) == expected


@pytest.mark.parametrize("nxt", EVIL_NEXT)
def test_open_redirect_is_blocked(anon_client: TestClient, nxt: str) -> None:
    assert nxt not in anon_client.get("/login", params={"next": nxt}).text  # the form's hidden field
    res = login(anon_client, nxt=nxt)
    assert res.status_code == 303 and res.headers["location"] == "/"
    res = anon_client.get("/login", params={"next": nxt}, follow_redirects=False)  # signed in now
    assert res.status_code == 303 and res.headers["location"] == "/"


@pytest.mark.parametrize("nxt,expected", [
    ("/?demo=1", "/"), ("/subscriptions/a", "/"), ("/api/subscriptions", "/"), ("/shop", "/shop"),
    ("/shop/penwright", "/shop/penwright"), ("/shopping", "/"), ("https://evil.example/shop/x", "/"),
])
def test_sign_in_lands_on_the_dashboard_or_a_shop(anon_client: TestClient, nxt: str, expected: str) -> None:
    res = login(anon_client, nxt=nxt)
    assert res.status_code == 303 and res.headers["location"] == expected
    assert safe_after_login(nxt) == expected


# ---- the wall ----------------------------------------------------------------------------------------------------
def test_signed_out_wall(anon_client: TestClient) -> None:
    c = anon_client
    home = c.get("/")
    assert home.status_code == 200 and 'data-testid="intro"' in home.text and 'data-testid="hi-name"' not in home.text
    res = c.get("/?demo=1", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/login?next=%2F%3Fdemo%3D1"
    res = c.get("/subscriptions/x", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/login?next=%2Fsubscriptions%2Fx"
    for path in ("/api/subscriptions", "/api/audit-log/verify", "/api/demo/state"):
        res = c.get(path)
        assert res.status_code == 401 and res.json() == {"detail": "Sign in first.", "rule_id": "AUTH"}, path
    assert c.post("/api/demo/reset").status_code == 401


def test_shop_is_public_but_checkout_needs_a_session(anon_client: TestClient) -> None:
    c = anon_client
    for public in ("/shop", "/shop/penwright", "/shop/penwright/terms", "/login", "/healthz",
                   "/static/dashboard.css", "/demo/paypal-autopay"):
        assert c.get(public, follow_redirects=False).status_code == 200, public
    checkout = {"merchant_id": "penwright", "plan_key": "penwright-pro", "user_id": "priya"}
    assert c.post("/api/checkout/create", json=checkout).status_code == 401
    register = {"paypal_id": "I-X", "merchant_id": "penwright", "plan_key": "penwright-pro", "user_id": "priya"}
    assert c.post("/api/subscriptions/register", json=register).status_code == 401


def test_other_user_in_query_is_403(client: TestClient) -> None:
    res = client.get("/api/subscriptions?user=intruder")
    assert res.status_code == 403 and res.json()["rule_id"] == "AUTH"
    assert client.get("/?user=intruder").status_code == 403
    assert client.get("/api/subscriptions?user=priya").status_code == 200
    rows = audit(client, "access_blocked", decision="blocked")
    assert [r["details"]["path"] for r in rows] == ["/api/subscriptions", "/"]
    assert all(r["user_id"] == "priya" and r["details"]["asked_user"] == ["intruder"] for r in rows)


def test_logout_clears_the_cookie_and_later_requests_are_signed_out(client: TestClient) -> None:
    assert client.get("/api/subscriptions").status_code == 200
    res = client.post("/logout", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/"
    assert f'{COOKIE}=""' in res.headers["set-cookie"] and "Max-Age=0" in res.headers["set-cookie"]
    assert COOKIE not in client.cookies
    assert signed_out(client)
    assert 'data-testid="intro"' in client.get("/").text
    assert client.get("/?demo=1", follow_redirects=False).status_code == 303


# ---- audit -------------------------------------------------------------------------------------------------------
def test_sign_in_events_are_audited_masked_and_without_the_password(anon_client: TestClient,
                                                                    settings: Settings) -> None:
    c = anon_client
    login(c, password="wrong-" + TEST_PASSWORD)
    login(c)
    c.post("/logout")
    assert c.get("/api/audit-log").status_code == 401  # signed out: the log isn't public
    login(c)
    (fail,) = audit(c, "sign_in_failed")
    assert fail["actor"] == "user" and fail["decision"] == "blocked" and fail["rule_id"] == "AUTH"
    ok = audit(c, "signed_in")[0]
    assert ok["actor"] == "user" and ok["decision"] == "allowed" and ok["user_id"] == "priya"
    (out,) = audit(c, "signed_out")
    assert out["decision"] == "allowed" and out["user_id"] == "priya"
    assert fail["details"]["email"] == ok["details"]["email"] == "p***@subguard-demo.example"
    log = (settings.runtime_dir / "audit_log.jsonl").read_text(encoding="utf-8")
    assert TEST_PASSWORD not in log and PRIYA_EMAIL not in log
    assert c.get("/api/audit-log/verify").json()["ok"] is True


# ---- startup -----------------------------------------------------------------------------------------------------
def test_mock_mode_without_password_starts_and_says_sign_in_is_off(data_dir: Path) -> None:
    s = Settings(_env_file=None, app_mode="mock", data_dir=data_dir, demo_seed=False)  # type: ignore[call-arg]
    with TestClient(create_app(s)) as c:
        assert c.get("/healthz").status_code == 200
        assert "Sign-in is off: set DEMO_PASSWORD in .env" in c.get("/login").text
        assert login(c, password="").status_code == 503
        assert 'data-testid="intro"' in c.get("/").text


@pytest.mark.parametrize("var", ["DEMO_PASSWORD", "SESSION_SECRET"])
def test_sandbox_without_a_sign_in_secret_fails_at_startup(var: str, tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here: only the variables below count
    env = {"APP_MODE": "sandbox", "PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret",
           "LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_MODEL": "model-x",
           "DEMO_PASSWORD": "pw", "SESSION_SECRET": "s" * 32, "DATA_DIR": str(tmp_path)}
    for name, value in {**env, var: ""}.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit, match=f"{var} is required in sandbox mode.*APP_MODE=mock"):
        create_app()

"""Sign-in smoke tests (Phase 7 Step 1, D-178..D-180). The full set arrives in Step 6."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE, safe_next, sign_session, verify_session
from app.config import Settings
from app.main import create_app
from tests.story_helpers import PRIYA_EMAIL, TEST_PASSWORD, audit


def login(c: TestClient, password: str = TEST_PASSWORD, email: str = PRIYA_EMAIL, nxt: str = "/"):  # noqa: ANN201
    return c.post("/login", data={"email": email, "password": password, "next": nxt}, follow_redirects=False)


def test_sign_in_sets_a_signed_cookie_and_is_audited(anon_client: TestClient, settings: Settings) -> None:
    c = anon_client
    res = login(c, email=PRIYA_EMAIL.upper(), nxt="/?demo=1")  # email compared case-insensitively
    assert res.status_code == 303 and res.headers["location"] == "/?demo=1"
    cookie = res.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie  # http here; Secure only over https
    assert verify_session(res.cookies[COOKIE], settings.session_secret) == "priya"
    assert c.get("/api/subscriptions").status_code == 200
    (row,) = audit(c, "signed_in")
    assert row["actor"] == "user" and row["decision"] == "allowed" and row["user_id"] == "priya"
    assert row["details"]["email"] == "p***@subguard-demo.example"
    log = (settings.runtime_dir / "audit_log.jsonl").read_text(encoding="utf-8")
    assert TEST_PASSWORD not in log and PRIYA_EMAIL not in log


def test_wrong_password_gets_the_generic_error(anon_client: TestClient) -> None:
    res = login(anon_client, password="nope")
    assert res.status_code == 401 and "Email or password is wrong" in res.text and COOKIE not in res.cookies
    assert login(anon_client, email="who@else.example").status_code == 401
    rows = [r for r in anon_client.app.state.store.audit.entries() if r.event == "sign_in_failed"]  # type: ignore[attr-defined]
    assert len(rows) == 2 and all(r.decision == "blocked" and r.actor == "user" for r in rows)


def test_rate_limit_after_five_failures(anon_client: TestClient) -> None:
    for _ in range(5):
        assert login(anon_client, password="nope").status_code == 401
    res = login(anon_client)  # right password, but this address is paused for a minute
    assert res.status_code == 429 and COOKIE not in res.cookies


def test_signed_out_wall(anon_client: TestClient) -> None:
    c = anon_client
    res = c.get("/?demo=1", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/login?next=%2F%3Fdemo%3D1"
    assert c.get("/subscriptions/x", follow_redirects=False).status_code == 303
    res = c.get("/api/subscriptions")
    assert res.status_code == 401 and res.json()["detail"] == "Sign in first."
    checkout = {"merchant_id": "penwright", "plan_key": "penwright-pro"}
    assert c.post("/api/checkout/create", json=checkout).status_code == 401
    for public in ("/login", "/healthz", "/shop/penwright", "/static/dashboard.css", "/demo/paypal-autopay"):
        assert c.get(public, follow_redirects=False).status_code == 200, public


def test_other_user_in_query_is_403(client: TestClient) -> None:
    res = client.get("/api/subscriptions?user=intruder")
    assert res.status_code == 403 and res.json()["rule_id"] == "AUTH"
    assert client.get("/?user=intruder").status_code == 403
    assert client.get("/api/subscriptions?user=priya").status_code == 200
    assert audit(client, "access_blocked", decision="blocked")


def test_logout_clears_the_cookie(client: TestClient) -> None:
    res = client.post("/logout", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/"
    assert f'{COOKIE}=""' in res.headers["set-cookie"] and "Max-Age=0" in res.headers["set-cookie"]
    assert client.get("/api/subscriptions").status_code == 401
    assert [e.event for e in client.app.state.store.audit.entries()].count("signed_out") == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize("target,expected", [
    ("/?demo=1", "/?demo=1"), ("/subscriptions/a", "/subscriptions/a"), ("//evil.example", "/"),
    ("/\\evil.example", "/"), ("https://evil.example/", "/"), ("javascript:alert(1)", "/"), ("", "/"),
])
def test_next_must_be_a_local_path(target: str, expected: str) -> None:
    assert safe_next(target) == expected


def test_tampered_or_expired_cookie_is_rejected() -> None:
    good = sign_session("priya", "k" * 32, 8)
    assert verify_session(good, "k" * 32) == "priya"
    assert verify_session(good, "x" * 32) is None
    assert verify_session(good[:-2] + "AA", "k" * 32) is None
    assert verify_session(sign_session("priya", "k" * 32, 1, now=0), "k" * 32) is None


def test_mock_mode_without_password_says_sign_in_is_off(data_dir: Path) -> None:
    s = Settings(_env_file=None, app_mode="mock", data_dir=data_dir, demo_seed=False)  # type: ignore[call-arg]
    with TestClient(create_app(s)) as c:
        assert "Sign-in is off: set DEMO_PASSWORD in .env" in c.get("/login").text
        assert login(c, password="").status_code == 503

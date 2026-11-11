"""Milestone 8: the Render Blueprint and the Zapier / outbox wiring."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.config import ROOT_DIR
from tests.story_helpers import advance_to, alerts, subscribe


def test_render_blueprint() -> None:
    bp = yaml.safe_load((ROOT_DIR / "render.yaml").read_text(encoding="utf-8"))
    (svc,) = bp["services"]
    assert svc["type"] == "web" and svc["runtime"] == "python" and svc["healthCheckPath"] == "/healthz"
    # Last command: one uvicorn worker. Before it, sandbox mode seeds the PayPal plans (D-158).
    assert svc["startCommand"].endswith("; python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT")
    assert 'if [ "$APP_MODE" = "sandbox" ]; then python scripts/seed_sandbox.py' in svc["startCommand"]
    assert svc["branch"] == "prototype-v3"
    assert "--reload" not in svc["startCommand"]
    assert "requirements.txt" in svc["buildCommand"]
    env = {e["key"]: e for e in svc["envVars"]}
    assert env["APP_MODE"]["value"] == "mock"
    assert env["WEB_CONCURRENCY"]["value"] == "1"  # one worker: uvicorn reads this as its default (D-020, D-100)
    for secret in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
                   "PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD", "PAYPAL_WEBHOOK_ID",
                   "ZAPIER_CATCH_HOOK_URL"):
        assert env[secret] == {"key": secret, "sync": False}  # never a value in git


def test_mock_mode_writes_the_outbox(demo_client: TestClient) -> None:
    """Mock mode: email/SMS for warning alerts land in data/runtime/outbox/ with the Zapier payload shape."""
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    (reminder,) = alerts(c, kind="reminder")
    assert reminder["delivery"] == {"in_app": "shown", "email": "mocked", "sms": "mocked"}
    outbox = Path(c.app.state.settings.runtime_dir) / "outbox"  # type: ignore[attr-defined]
    payloads = [json.loads(f.read_text(encoding="utf-8")) for f in outbox.glob("*.json")]
    mine = [p for p in payloads if p["idempotency_key"] == reminder["idempotency_key"]]
    assert sorted(p["channel"] for p in mine) == ["email", "sms"]
    assert set(mine[0]) >= {"type", "to", "subject", "body", "cta_url", "idempotency_key", "channels"}
    assert mine[0]["type"] == "user_alert" and mine[0]["to"]["email"] == "priya@subguard-demo.example"
    start = c.get("/api/audit-log?event=startup").json()[0]
    assert start["details"]["notify"] == "outbox"

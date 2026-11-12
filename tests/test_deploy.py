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
    assert svc["name"] == "subguard-demo" and svc["plan"] == "free" and svc["autoDeploy"] is True
    assert svc["branch"] == "main"
    assert svc["buildCommand"] == "pip install --upgrade pip && pip install -r requirements.txt"
    # Sandbox mode seeds the PayPal plans first (D-158); then one uvicorn worker behind Render's proxy (D-183).
    assert svc["startCommand"] == (
        'if [ "$APP_MODE" = "sandbox" ]; then python scripts/seed_sandbox.py || echo "seed failed: see logs"; fi; '
        "python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'")
    assert "--reload" not in svc["startCommand"] and "--workers" not in svc["startCommand"]
    assert svc["envVars"] == [
        {"key": "PYTHON_VERSION", "value": "3.12.10"},
        {"key": "APP_MODE", "value": "mock"},
        {"key": "WEB_CONCURRENCY", "value": "1"},  # one worker: uvicorn reads this as its default (D-020, D-100)
        {"key": "DEMO_SEED", "value": "true"},
        {"key": "LLM_PROVIDER", "value": "anthropic"},
        {"key": "AUTO_APPROVE_MODE", "value": "auto"},  # D-192: Render (RENDER env) -> PayPal's own button
        {"key": "SHOW_SANDBOX_BUYER", "value": "true"},  # D-192: sandbox only; the login itself is a dashboard secret
        {"key": "SESSION_SECRET", "generateValue": True},  # generated once by Render, kept across restarts
        *({"key": k, "sync": False} for k in (  # secrets: never a value in git
            "DEMO_PASSWORD", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
            "PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD", "PAYPAL_WEBHOOK_ID",
            "ZAPIER_CATCH_HOOK_URL")),
    ]


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

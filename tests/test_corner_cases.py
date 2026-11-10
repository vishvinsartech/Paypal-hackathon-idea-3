"""Corner cases from spec section 8 that aren't covered elsewhere: 2, 6, 8, 16, 27, 35, 37.
(The full map, case by case, is in docs/CORNER_CASES.md.)"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.savings import money_protected, protected_by_currency
from app.integrations.notify import Notifier, warning_basis
from app.integrations.paypal_gateway import Ctx
from app.integrations.paypal_types import SubscriptionView
from app.models import ConsentSnapshot, Subscription
from app.pricing import Pricing
from app.routes import subscriptions as subs_route
from tests.story_helpers import advance_to, alerts, audit, sub, subscribe


# ---- 2: onApprove fires but PayPal still says APPROVED -> poll until ACTIVE --------------------------
class SlowGateway:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.calls = 0

    async def get_subscription(self, paypal_id: str, ctx: Ctx) -> SubscriptionView:
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        return SubscriptionView(id=paypal_id, status=status)  # type: ignore[call-arg]


async def test_register_polls_until_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subs_route, "POLL_INTERVAL", 0)
    gw = SlowGateway(["APPROVAL_PENDING", "APPROVED", "ACTIVE"])
    view = await subs_route._wait_active(gw, "I-1", Ctx(actor="user"), timeout=5)  # type: ignore[arg-type]
    assert view.status == "ACTIVE" and gw.calls == 3


async def test_register_gives_up_if_never_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subs_route, "POLL_INTERVAL", 0.01)
    gw = SlowGateway(["APPROVED"])
    view = await subs_route._wait_active(gw, "I-1", Ctx(actor="user"), timeout=0.05)  # type: ignore[arg-type]
    assert view.status == "APPROVED"  # the route then answers 202: no snapshot, no timer


# ---- 6: duplicate webhooks, webhook + poller on the same change ------------------------------------------
def hook(c: TestClient, event_id: str, kind: str, paypal_id: str, **resource: Any) -> dict[str, Any]:
    res = c.post("/webhooks/paypal", json={"id": event_id, "event_type": kind,
                                           "resource": {"id": paypal_id, **resource}})
    assert res.status_code == 200, res.text
    return res.json()


def test_webhook_dedupe_by_event_id_and_status_transition(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    assert hook(c, "WH-1", "BILLING.SUBSCRIPTION.SUSPENDED", main["paypal_id"]) == {"status": "processed",
                                                                                   "changed": True}
    assert hook(c, "WH-1", "BILLING.SUBSCRIPTION.SUSPENDED", main["paypal_id"]) == {"status": "duplicate"}
    # a different event for the same transition changes nothing
    assert hook(c, "WH-2", "BILLING.SUBSCRIPTION.SUSPENDED", main["paypal_id"])["changed"] is False
    assert sub(c, main["id"])["status"] == "SUSPENDED"
    assert all(t["status"] == "CANCELLED" for t in c.get("/api/timers?user=usera").json())  # corner case 5
    assert len(audit(c, "status_sync", subscription_id=main["id"])) == 1
    assert audit(c, "webhook_duplicate")


def test_webhook_then_poller_sees_the_same_change_once(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    mock = c.app.state.gateway.mock  # type: ignore[attr-defined]
    c.portal.call(mock.set_status, main["paypal_id"], "SUSPENDED")  # type: ignore[union-attr]
    hook(c, "WH-9", "BILLING.SUBSCRIPTION.SUSPENDED", main["paypal_id"])
    advance_to(c, 1)  # the tick's poller sees SUSPENDED too
    rows = audit(c, "status_sync", subscription_id=main["id"])
    assert len(rows) == 1 and rows[0]["details"]["source"] == "webhook"


def test_webhook_unknown_or_malformed(demo_client: TestClient) -> None:
    assert hook(demo_client, "WH-3", "BILLING.SUBSCRIPTION.CANCELLED", "I-NOPE") == {"status": "ignored"}
    assert demo_client.post("/webhooks/paypal", json={"nope": 1}).status_code == 400
    assert demo_client.post("/webhooks/paypal", content=b"not json").status_code == 400


def test_webhook_signature_required_in_sandbox(demo_client: TestClient) -> None:
    app = demo_client.app
    app.state.services.settings = app.state.services.settings.model_copy(update={"app_mode": "sandbox"})  # type: ignore[attr-defined]

    async def bad(headers: dict[str, str], event: dict[str, Any]) -> bool:
        return False

    app.state.verify_webhook = bad  # type: ignore[attr-defined]
    res = demo_client.post("/webhooks/paypal", json={"id": "WH-4", "event_type": "PAYMENT.SALE.COMPLETED"})
    assert res.status_code == 400 and audit(demo_client, "webhook_rejected")


# ---- 8: non-USD plans: format with the plan's currency, never add currencies into one KPI --------------
def _cancelled(sid: str, currency: str, amount: str) -> Subscription:
    snap = ConsentSnapshot(taken_at=datetime(2026, 1, 1), sim_day=0, price=Decimal("1"), currency=currency)
    return Subscription(id=sid, paypal_id=sid, plan_key="x", plan_id="x", merchant_id="m", owner_id="usera",
                        status="CANCELLED", cancelled_by="user", protected_year_usd=Decimal(amount),
                        consent_snapshot=snap)


def test_currencies_never_mixed_in_kpi() -> None:
    subs = [_cancelled("a", "USD", "100.00"), _cancelled("b", "EUR", "50.00"), _cancelled("c", "USD", "1.50")]
    assert money_protected(subs, "usera", "USD") == Decimal("101.50")
    assert protected_by_currency(subs, "usera") == {"USD": Decimal("101.50"), "EUR": Decimal("50.00")}
    p = Pricing()
    assert (p.money("12", "EUR"), p.money("9.99", "GBP"), p.money("5", "JPY"), p.money("20")) == (
        "€12", "£9.99", "5 JPY", "$20")


def test_kpi_reports_other_currencies_separately(demo_client: TestClient) -> None:
    store = demo_client.app.state.store  # type: ignore[attr-defined]
    with store.edit("subscriptions") as subs:
        subs.items.append(_cancelled("sub-eur", "EUR", "60.00"))
    k = demo_client.get("/api/kpis?user=usera").json()
    assert k["money_protected"] == "0.00" and k["other_currencies"] == {"EUR": "€60"}


# ---- 16: times in UTC, sim days are integers -------------------------------------------------------------
def test_times_are_utc_and_days_are_ints(demo_client: TestClient) -> None:
    subscribe(demo_client)
    for row in demo_client.get("/api/audit-log").json():
        assert row["ts"].endswith(("+00:00", "Z")) and isinstance(row["sim_day"], int)
    for t in demo_client.get("/api/timers?user=usera").json():
        assert all(isinstance(t[k], int) for k in ("fire_day", "deadline_day", "reminder_day", "billing_day"))


# ---- 27: "trial ends early after 3 exports" ------------------------------------------------------------
def test_too_many_exports_warns_and_moves_deadline(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 2)
    for _ in range(3):
        assert c.post("/shop/penwright/app/export?user=usera").status_code == 200
    advance_to(c, 3)
    assert alerts(c, kind="early_trial_end") == []  # 3 exports is still within "more than 3"
    page = c.post("/shop/penwright/app/export?user=usera").text
    assert 'data-testid="app-exports">4<' in page
    advance_to(c, 4)
    (alert,) = alerts(c, kind="early_trial_end")
    assert "exported 4 documents" in alert["body"] and alert["level"] == "urgent"
    assert [a["action"] for a in alert["actions"]] == ["cancel", "keep"]
    timer = next(t for t in c.get("/api/timers?user=usera").json() if t["subscription_id"] == main["id"])
    assert timer["deadline_day"] == 4 and "ended early" in timer["note"]
    assert audit(c, "early_trial_end_risk", subscription_id=main["id"])
    advance_to(c, 5)
    assert len(alerts(c, kind="early_trial_end")) == 1  # once only


# ---- 37: Zapier down -> retry with backoff, then failed (feeds R2); in-app still works --------------------
def zapier_settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, app_mode="sandbox", data_dir=tmp_path,  # type: ignore[call-arg]
                    zapier_catch_hook_url="https://hooks.zapier.example/hooks/catch/1/abc")


@respx.mock
async def test_zapier_retries_then_fails(tmp_path: Path) -> None:
    route = respx.post("https://hooks.zapier.example/hooks/catch/1/abc").mock(return_value=httpx.Response(503))
    n = Notifier(zapier_settings(tmp_path), tmp_path / "outbox", retry_delays=(0, 0, 0))
    out = await n.send(kind="user_alert", to={"email": "p@example.com"}, subject="s", body="b",
                       idempotency_key="k", channels=["email", "sms"])
    assert out == {"email": "failed", "sms": "failed"} and route.call_count == 4  # 1 try + 3 retries
    assert warning_basis({"in_app": "shown", **out}) == (True, "zapier_down_in_app_only")


@respx.mock
async def test_zapier_accepts_after_a_retry(tmp_path: Path) -> None:
    route = respx.post("https://hooks.zapier.example/hooks/catch/1/abc").mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(200)])
    n = Notifier(zapier_settings(tmp_path), tmp_path / "outbox", retry_delays=(0, 0, 0))
    out = await n.send(kind="user_alert", to={}, subject="s", body="b", idempotency_key="k", channels=["email"])
    assert out == {"email": "accepted"} and route.call_count == 2
    assert route.calls[0].request.content == route.calls[1].request.content  # same payload + idempotency key
    assert warning_basis({"in_app": "shown", **out}) == (True, "zapier_accepted")


# ---- the map in docs/CORNER_CASES.md stays honest -------------------------------------------------------------
def test_corner_case_map_lists_all_39_and_real_tests() -> None:
    import re

    root = Path(__file__).resolve().parent
    doc = (root.parent / "docs" / "CORNER_CASES.md").read_text(encoding="utf-8")
    assert sorted({int(n) for n in re.findall(r"^\| (\d+) \|", doc, re.M)}) == list(range(1, 40))
    for file, test in set(re.findall(r"`(test_\w+)::(test_\w+)`", doc)):
        assert re.search(rf"def {test}\(", (root / f"{file}.py").read_text(encoding="utf-8")), f"{file}::{test}"

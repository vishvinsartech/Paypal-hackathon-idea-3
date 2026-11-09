"""Mock-mode checkout API: create -> approve -> register (+ add-on), consent snapshot, pending, ownership."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient


def buy(client: TestClient, plan_key: str = "penwright-pro", merchant: str = "penwright", user: str = "priya",
        approve: bool = True, addon_of: str | None = None) -> tuple[str, object]:
    created = client.post("/api/checkout/create", json={"merchant_id": merchant, "plan_key": plan_key,
                                                          "user_id": user}).json()
    if approve:
        assert client.post("/api/checkout/mock-approve", json={"paypal_id": created["paypal_id"]}).json()[
            "status"] == "ACTIVE"
    reg = client.post("/api/subscriptions/register", json={
        "paypal_id": created["paypal_id"], "merchant_id": merchant, "plan_key": plan_key, "user_id": user,
        "addon_of": addon_of})
    return created["paypal_id"], reg


def test_register_penwright_with_addon(client: TestClient) -> None:
    pid, reg = buy(client)
    assert reg.status_code == 200  # type: ignore[attr-defined]
    sub = reg.json()  # type: ignore[attr-defined]
    assert sub["status"] == "ACTIVE" and sub["owner_id"] == "priya" and sub["signup_day"] == 0
    assert sub["next_billing_day"] == 15  # 14-day trial from Day 0 -> first charge Day 15
    snap = sub["consent_snapshot"]
    assert Decimal(snap["price"]) == Decimal("24.99") and len(snap["billing_cycles"]) == 3

    _, addon = buy(client, plan_key="penwright-ai-pack", addon_of=sub["id"])
    assert addon.json()["addon_of"] == sub["id"]  # type: ignore[attr-defined]
    assert addon.json()["next_billing_day"] == 30  # type: ignore[attr-defined]

    mine = client.get("/api/subscriptions?user=priya").json()
    assert {s["plan_key"] for s in mine} == {"penwright-pro", "penwright-ai-pack"}
    assert client.get("/api/subscriptions?user=john").json() == []
    events = [e["event"] for e in client.get("/api/audit-log").json()]
    assert events.count("subscription_registered") == 2 and events.count("consent_snapshot") == 2


def test_unapproved_subscription_is_not_registered(client: TestClient) -> None:
    """Corner case 1/2: no approval -> 202, no snapshot, nothing stored."""
    _, reg = buy(client, approve=False)
    assert reg.status_code == 202 and reg.json() == {"registered": False, "status": "APPROVAL_PENDING"}  # type: ignore[attr-defined]
    assert client.get("/api/subscriptions?user=priya").json() == []


def test_register_is_idempotent_and_owner_checked(client: TestClient) -> None:
    pid, first = buy(client, plan_key="framewise-basic", merchant="framewise")
    again = client.post("/api/subscriptions/register", json={
        "paypal_id": pid, "merchant_id": "framewise", "plan_key": "framewise-basic", "user_id": "priya"})
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]  # type: ignore[attr-defined]
    stolen = client.post("/api/subscriptions/register", json={
        "paypal_id": pid, "merchant_id": "framewise", "plan_key": "framewise-basic", "user_id": "john"})
    assert stolen.status_code == 409


def test_bad_inputs(client: TestClient) -> None:
    assert client.post("/api/checkout/create", json={"merchant_id": "nope", "plan_key": "x"}).status_code == 404
    assert client.post("/api/checkout/create", json={"merchant_id": "lumen", "plan_key": "penwright-pro"}
                       ).status_code == 404
    assert client.post("/api/checkout/create", json={"merchant_id": "lumen", "plan_key": "lumen-monthly",
                                                     "user_id": "mallory"}).status_code == 404


def test_unknown_paypal_id_gives_friendly_502(client: TestClient) -> None:
    r = client.post("/api/subscriptions/register", json={
        "paypal_id": "I-NOPE", "merchant_id": "lumen", "plan_key": "lumen-monthly", "user_id": "john"})
    assert r.status_code == 502 and "PayPal" in r.json()["error"] and "Traceback" not in r.text


def test_shop_checkout_script_served(client: TestClient) -> None:
    assert 'src="/shop/static/checkout.js"' in client.get("/shop/penwright").text
    assert client.get("/shop/static/checkout.js").status_code == 200

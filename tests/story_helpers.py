"""Helpers for the Story A / B tests (the `demo_client` fixture lives in conftest.py)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def subscribe(client: TestClient, merchant: str, plan_key: str, user: str = "priya", addon_key: str | None = None,
              review: bool = True) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """What the shop does: companion preflight -> create -> mock approve -> register (+ ticked add-on)."""
    review_id = None
    if review:
        res = client.post("/api/review/preflight", json={"merchant_url": f"/shop/{merchant}", "plan_key": plan_key,
                                                         "user_id": user})
        review_id = res.json()["review_id"]

    def one(key: str, addon_of: str | None) -> dict[str, Any]:
        created = client.post("/api/checkout/create", json={"merchant_id": merchant, "plan_key": key,
                                                            "user_id": user}).json()
        client.post("/api/checkout/mock-approve", json={"paypal_id": created["paypal_id"]})
        res = client.post("/api/subscriptions/register", json={
            "paypal_id": created["paypal_id"], "merchant_id": merchant, "plan_key": key, "user_id": user,
            "addon_of": addon_of, "review_id": review_id if addon_of is None else None})
        assert res.status_code == 200, res.text
        return res.json()

    main = one(plan_key, None)
    return main, (one(addon_key, main["id"]) if addon_key else None)


def alerts(client: TestClient, user: str = "priya", kind: str | None = None) -> list[dict[str, Any]]:
    return [a for a in client.get(f"/api/alerts?user={user}").json() if kind is None or a["kind"] == kind]


def audit(client: TestClient, event: str | None = None, **match: Any) -> list[dict[str, Any]]:
    rows = client.get("/api/audit-log" + (f"?event={event}" if event else "")).json()
    return [r for r in rows if all(r.get(k) == v for k, v in match.items())]


def advance_to(client: TestClient, day: int) -> None:
    assert client.post(f"/api/demo/advance?to_day={day}").json()["sim_day"] == day


def sub(client: TestClient, sub_id: str, user: str = "priya") -> dict[str, Any]:
    return next(s for s in client.get(f"/api/subscriptions?user={user}").json() if s["id"] == sub_id)


def cancel_via_alert(client: TestClient, alert: dict[str, Any], action: str = "cancel",
                     user: str = "priya") -> tuple[dict[str, Any], dict[str, Any]]:
    card = client.post(f"/api/alerts/{alert['id']}/act", json={"user_id": user, "action": action}).json()["confirm"]
    done = client.post("/api/agent/confirm", json={"user_id": user, "token": card["token"],
                                                   "subscription_ids": [i["subscription_id"] for i in card["items"]]})
    return card, done.json()

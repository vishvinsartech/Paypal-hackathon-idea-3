"""Helpers for the demo-story tests (the `demo_client` fixture lives in conftest.py)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.core.sub_dates import cal
from app.models import User
from app.store import utcnow


def on(days: int) -> str:
    """The calendar date `days` after a sign-up made now, as SubGuard writes it ("Nov 18")."""
    return cal(utcnow() + timedelta(days=days))


ACT_BY = f"Act by {on(7)} (the terms allow {on(8)})"  # D6 wording for a Day 0 Penwright sign-up


def allow_many(client: TestClient) -> TestClient:
    """Lift D-172's one-subscription-per-merchant rule, for tests that need two Penwright subscriptions."""
    client.app.state.services.settings.one_sub_per_merchant = False  # type: ignore[attr-defined]
    return client


def subscribe(client: TestClient, merchant: str = "penwright", plan_key: str = "penwright-pro", user: str = "priya",
              review: bool = True) -> dict[str, Any]:
    """What the shop does: companion preflight -> create -> mock approve -> register."""
    review_id = None
    if review:
        res = client.post("/api/review/preflight", json={"merchant_url": f"/shop/{merchant}", "plan_key": plan_key,
                                                         "user_id": user})
        review_id = res.json()["review_id"]
    created = client.post("/api/checkout/create", json={"merchant_id": merchant, "plan_key": plan_key,
                                                        "user_id": user}).json()
    client.post("/api/checkout/mock-approve", json={"paypal_id": created["paypal_id"]})
    res = client.post("/api/subscriptions/register", json={
        "paypal_id": created["paypal_id"], "merchant_id": merchant, "plan_key": plan_key, "user_id": user,
        "review_id": review_id})
    assert res.status_code == 200, res.text
    return res.json()


def add_user(client: TestClient, user_id: str = "intruder") -> str:
    """A second, test-only user for the R5 ownership checks (the demo itself has only Priya)."""
    store = client.app.state.store  # type: ignore[attr-defined]
    with store.edit("users") as users:
        if not any(u.id == user_id for u in users.items):
            users.items.append(User(id=user_id, name=user_id.title(), email=f"{user_id}@subguard-demo.example"))
    return user_id


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

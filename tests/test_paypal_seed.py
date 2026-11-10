"""Sandbox seeding (no network): idempotent reuse, re-create on price change, PayPal plan-shape rules."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.config import Settings
from app.integrations.paypal_seed import Seeder, check_paypal_settings, plan_matches
from app.integrations.paypal_types import PayPalError, PlanView, first_charge_day, first_paid_price
from app.models import PlanDef
from app.pricing import Pricing
from app.store import JsonStore


class FakeRest:
    def __init__(self) -> None:
        self.products: dict[str, dict[str, Any]] = {}
        self.created: list[str] = []

    async def get_json(self, path: str) -> dict[str, Any]:
        pid = path.rsplit("/", 1)[-1]
        if pid not in self.products:
            raise PayPalError("not found", status=404, name="RESOURCE_NOT_FOUND")
        return self.products[pid]

    async def create_product(self, name: str, *, request_id: str, description: str = "") -> dict[str, Any]:
        pid = f"PROD-{len(self.products) + 1}"
        self.products[pid] = {"id": pid, "name": name}
        self.created.append(request_id)
        return self.products[pid]


class FakeSdk:
    def __init__(self) -> None:
        self.plans: dict[str, PlanView] = {}
        self.request_ids: list[str] = []

    async def get_plan(self, plan_id: str) -> PlanView:
        if plan_id not in self.plans:
            raise PayPalError("not found", status=404, name="RESOURCE_NOT_FOUND")
        return self.plans[plan_id]

    async def create_plan(self, product_id: str, plan: PlanDef, *, request_id: str) -> PlanView:
        pid = f"P-{len(self.plans) + 1:012d}"
        self.plans[pid] = PlanView(id=pid, name=plan.name, status="ACTIVE", currency=plan.currency,
                                   billing_cycles=plan.billing_cycles)
        self.request_ids.append(request_id)
        return self.plans[pid]


def seeder(store: JsonStore, sdk: FakeSdk, rest: FakeRest) -> Seeder:
    return Seeder(store, sdk, rest)  # type: ignore[arg-type]


async def test_seed_creates_everything_then_reuses(store: JsonStore) -> None:
    sdk, rest = FakeSdk(), FakeRest()
    items = await seeder(store, sdk, rest).run()
    ids = store.load("sandbox_ids")
    assert set(ids.products) == {"penwright"}
    assert set(ids.plans) == {"penwright-pro"}
    assert all(i.action == "created" for i in items) and len(items) == 2
    again = await seeder(store, sdk, rest).run()
    assert all(i.action == "reused" for i in again)
    assert len(sdk.plans) == 1 and len(rest.products) == 1
    events = [e for e in store.audit.query() if e.event == "sandbox_seed"]
    assert len(events) == 2  # reuse writes nothing


async def test_price_change_creates_a_new_plan(store: JsonStore, data_dir: Any) -> None:
    sdk, rest = FakeSdk(), FakeRest()
    await seeder(store, sdk, rest).run()
    old = store.load("sandbox_ids").plans["penwright-pro"]
    pricier = JsonStore(data_dir / "runtime", data_dir / "seed",
                        pricing=Pricing(penwright_step_up_price=Decimal("59.99")))
    items = await seeder(pricier, sdk, rest).run()
    new = pricier.load("sandbox_ids").plans["penwright-pro"]
    assert new != old
    assert {i.key: i.action for i in items} == {"penwright": "reused", "penwright-pro": "replaced"}


async def test_missing_remote_plan_or_inactive_plan_is_recreated(store: JsonStore) -> None:
    sdk, rest = FakeSdk(), FakeRest()
    await seeder(store, sdk, rest).run()
    ids = store.load("sandbox_ids")
    del sdk.plans[ids.plans["penwright-pro"]]
    assert {i.key: i.action for i in await seeder(store, sdk, rest).run()}["penwright-pro"] == "replaced"
    ids = store.load("sandbox_ids")
    sdk.plans[ids.plans["penwright-pro"]].status = "INACTIVE"
    assert {i.key: i.action for i in await seeder(store, sdk, rest).run()}["penwright-pro"] == "replaced"


def test_plans_respect_paypal_shape_rules() -> None:
    """PayPal: at most one REGULAR cycle, at most two TRIAL cycles, TRIAL before REGULAR (D-031)."""
    p = Pricing()
    assert p.plans_for("framewise") == [] and p.plans_for("lumen") == []  # one merchant since D-090
    for merchant in ("penwright",):
        for plan in p.plans_for(merchant):
            kinds = [c.tenure_type for c in plan.billing_cycles]
            assert kinds.count("REGULAR") == 1 and kinds.count("TRIAL") <= 2
            assert kinds == sorted(kinds, key=lambda k: k != "TRIAL")


def test_paid_trial_does_not_delay_first_charge() -> None:
    pro = Pricing().plans_for("penwright")[0]
    assert first_charge_day(pro.billing_cycles, 0) == 11
    assert first_paid_price(pro.billing_cycles) == Decimal("24.99")


def test_plan_matches_compares_cycles_and_currency() -> None:
    plan = Pricing().plans_for("penwright")[0]
    view = PlanView(id="P-1", status="ACTIVE", currency="USD", billing_cycles=plan.billing_cycles)
    assert plan_matches(plan, view)
    assert not plan_matches(plan, view.model_copy(update={"currency": "EUR"}))


def test_seed_settings_check_needs_only_paypal() -> None:
    s = Settings(_env_file=None, app_mode="sandbox")  # type: ignore[call-arg]
    assert any("PAYPAL_CLIENT_ID" in p for p in check_paypal_settings(s))
    ok = Settings(_env_file=None, app_mode="sandbox", paypal_client_id="a", paypal_client_secret="b")  # type: ignore[call-arg]
    assert check_paypal_settings(ok) == []

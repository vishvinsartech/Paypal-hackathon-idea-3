"""Idempotent sandbox seeding (`make seed`, spec 7.1): one product per merchant, one plan per PlanDef.

Plans are built from `settings.pricing` (.env prices, DECISIONS D-015). A stored plan id is reused only
if PayPal's copy is ACTIVE and its billing cycles match the current pricing exactly. Otherwise a new plan
is created (PayPal can't change a plan's cycle structure) and `sandbox_ids.json` is updated.
Request ids are derived from the content, so re-running after a lost `sandbox_ids.json` doesn't
duplicate anything PayPal still remembers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.config import SANDBOX_API_BASE, Settings
from app.integrations.paypal_rest import PayPalRest
from app.integrations.paypal_sdk import SdkPayPal, plan_request
from app.integrations.paypal_types import PayPalError, PlanView
from app.models import Merchant, PlanDef, SandboxIds
from app.store import JsonStore


@dataclass
class SeedItem:
    kind: str  # product | plan
    key: str
    paypal_id: str
    action: str  # reused | created | replaced


def check_paypal_settings(s: Settings) -> list[str]:
    """Only the PayPal half of validate_settings: seeding needs no LLM key."""
    problems = []
    if s.paypal_api_base.rstrip("/") != SANDBOX_API_BASE:
        problems.append(f"PAYPAL_API_BASE must be {SANDBOX_API_BASE} (sandbox only).")
    if s.paypal_environment.upper() != "SANDBOX":
        problems.append("PAYPAL_ENVIRONMENT must be SANDBOX.")
    for name in ("paypal_client_id", "paypal_client_secret"):
        if not getattr(s, name):
            problems.append(f"{name.upper()} is required to seed the sandbox.")
    return problems


def _digest(obj: Any) -> str:
    return hashlib.sha256(repr(obj).encode()).hexdigest()[:16]


def cycle_signature(currency: str, cycles: list[Any]) -> tuple[Any, ...]:
    return (currency, *((c.tenure_type, f"{c.price:.2f}", c.interval_unit, c.interval_count, c.total_cycles)
                        for c in cycles))


def plan_matches(want: PlanDef, have: PlanView) -> bool:
    return (have.status == "ACTIVE"
            and cycle_signature(want.currency, want.billing_cycles) == cycle_signature(have.currency,
                                                                                       have.billing_cycles))


class Seeder:
    def __init__(self, store: JsonStore, sdk: SdkPayPal, rest: PayPalRest) -> None:
        self.store = store
        self.sdk = sdk
        self.rest = rest

    async def _exists(self, path: str) -> dict[str, Any] | None:
        try:
            return await self.rest.get_json(path)
        except PayPalError as exc:
            if exc.status == 404 or "INVALID_RESOURCE_ID" in exc.issues or exc.name == "RESOURCE_NOT_FOUND":
                return None
            raise

    async def ensure_product(self, merchant: Merchant, ids: SandboxIds) -> SeedItem:
        pid = ids.products.get(merchant.id)
        if pid and await self._exists(f"/v1/catalogs/products/{pid}"):
            return SeedItem("product", merchant.id, pid, "reused")
        data = await self.rest.create_product(
            f"{merchant.name} (SubGuard demo)", request_id=f"subguard-seed-product-{merchant.id}",
            description=f"Fictional merchant for the SubGuard demo. {merchant.tagline}"[:256])
        ids.products[merchant.id] = data["id"]
        return SeedItem("product", merchant.id, data["id"], "replaced" if pid else "created")

    async def ensure_plan(self, product_id: str, plan: PlanDef, ids: SandboxIds) -> SeedItem:
        old = ids.plans.get(plan.key)
        if old:
            try:
                if plan_matches(plan, await self.sdk.get_plan(old)):
                    return SeedItem("plan", plan.key, old, "reused")
            except PayPalError as exc:
                if exc.status != 404 and exc.name != "RESOURCE_NOT_FOUND":
                    raise
        rid = f"subguard-seed-plan-{plan.key}-{_digest(plan_request(product_id, plan))}"
        view = await self.sdk.create_plan(product_id, plan, request_id=rid)
        ids.plans[plan.key] = view.id
        return SeedItem("plan", plan.key, view.id, "replaced" if old else "created")

    async def run(self) -> list[SeedItem]:
        ids: SandboxIds = self.store.load("sandbox_ids")
        merchants = self.store.load("merchants").items
        items: list[SeedItem] = []
        try:
            for merchant in merchants:
                product = await self.ensure_product(merchant, ids)
                items.append(product)
                for plan in self.store.pricing.plans_for(merchant.id):
                    items.append(await self.ensure_plan(product.paypal_id, plan, ids))
        finally:  # keep whatever was created even if a later call fails
            self.store.save("sandbox_ids", ids)
        for item in items:
            if item.action != "reused":
                self.store.audit.append(actor="system", event="sandbox_seed", transport="rest"
                                        if item.kind == "product" else "sdk", result=item.action,
                                        details={"kind": item.kind, "key": item.key, "paypal_id": item.paypal_id})
        return items

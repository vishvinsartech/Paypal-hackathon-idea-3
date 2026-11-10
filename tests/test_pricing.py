"""Demo prices/terms come from .env (app/pricing.py) and flow everywhere: plans, mock PayPal, shop text."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings, load_settings
from app.main import create_app
from app.pricing import Pricing
from app.store import JsonStore


def test_defaults_are_the_spec_numbers() -> None:
    p = Pricing()
    assert (p.penwright_trial_days, p.penwright_intro_price, p.penwright_intro_months) == (10, Decimal("24.99"), 3)
    assert p.penwright_step_up_price == Decimal("49.99")
    assert (p.penwright_notice_days, p.penwright_export_limit, p.penwright_first_charge_day) == (3, 3, 11)
    assert not {"penwright_addon_price", "framewise_price", "lumen_monthly_price"} & set(Pricing.model_fields)
    pro = p.plans_for("penwright")[0]
    cycles = [(c.tenure_type, c.price, c.interval_unit, c.interval_count, c.total_cycles) for c in pro.billing_cycles]
    assert cycles == [
        ("TRIAL", Decimal("0.00"), "DAY", 10, 1), ("TRIAL", Decimal("24.99"), "MONTH", 1, 3),
        ("REGULAR", Decimal("49.99"), "MONTH", 1, 0)]
    assert Settings(_env_file=None).pricing == p  # type: ignore[call-arg]


def test_money_display() -> None:
    p = Pricing()
    assert p.money(Decimal("20.00")) == "$20" and p.money(Decimal("24.99")) == "$24.99" and p.money(0) == "$0"
    assert Pricing(demo_currency="EUR").money(Decimal("12")) == "€12"
    assert Pricing(demo_currency="CHF").money(Decimal("12.50")) == "12.50 CHF"


def test_env_vars_override_pricing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PENWRIGHT_INTRO_PRICE", "29.99")
    monkeypatch.setenv("PENWRIGHT_TRIAL_DAYS", "10")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = load_settings()
    assert s.pricing.penwright_intro_price == Decimal("29.99") and s.pricing.penwright_first_charge_day == 11


@pytest.mark.parametrize(("var", "value"), [
    ("PENWRIGHT_INTRO_PRICE", "-5"), ("PENWRIGHT_INTRO_PRICE", "24.999"), ("PENWRIGHT_STEP_UP_PRICE", "abc"),
    ("PENWRIGHT_TRIAL_DAYS", "0"), ("DEMO_CURRENCY", "usd"),
])
def test_invalid_values_fail_with_clear_message(monkeypatch: pytest.MonkeyPatch, var: str, value: str) -> None:
    monkeypatch.setenv(var, value)
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert var in str(exc.value) and "Traceback" not in str(exc.value)


@pytest.fixture
def custom_client(data_dir: Path) -> TestClient:
    s = Settings(_env_file=None, app_mode="mock", data_dir=data_dir,  # type: ignore[call-arg]
                 penwright_trial_days=10, penwright_intro_price=Decimal("29.99"),
                 penwright_step_up_price=Decimal("59"), penwright_notice_days=5)
    with TestClient(create_app(s)) as c:
        yield c  # type: ignore[misc]


def test_custom_prices_flow_to_plans_shop_and_checkout(custom_client: TestClient) -> None:
    c = custom_client
    pen = c.get("/shop/penwright").text
    assert "Start your 10-day free trial — $0 today" in pen
    assert "Penwright Pro at $29.99/month, with the first charge on day 11" in pen
    assert "becomes $59/month" in pen and "at least 5 days before" in pen
    assert "$24.99" not in pen and "$49.99" not in pen
    assert "so the real deadline is Day 5." in c.get("/shop").text  # 11 - 5 - 1, inside "Show what's hidden"

    created = c.post("/api/checkout/create", json={"merchant_id": "penwright", "plan_key": "penwright-pro"}).json()
    c.post("/api/checkout/mock-approve", json={"paypal_id": created["paypal_id"]})
    sub = c.post("/api/subscriptions/register", json={"paypal_id": created["paypal_id"], "merchant_id": "penwright",
                                                      "plan_key": "penwright-pro"}).json()
    assert Decimal(sub["consent_snapshot"]["price"]) == Decimal("29.99") and sub["next_billing_day"] == 11
    assert [Decimal(cy["price"]) for cy in sub["consent_snapshot"]["billing_cycles"]] == [
        Decimal("0"), Decimal("29.99"), Decimal("59")]


def test_changed_prices_warn_until_reset(data_dir: Path) -> None:
    runtime, seed = data_dir / "runtime", data_dir / "seed"
    old = JsonStore(runtime, seed)
    old.ensure_all()
    old.check_pricing()
    assert old.warnings == []

    new = JsonStore(runtime, seed, pricing=Pricing(penwright_intro_price=Decimal("29.99")))
    new.check_pricing()
    assert any("make reset" in w for w in new.warnings)
    penwright = next(mc for mc in new.load("merchants").items if mc.id == "penwright")
    assert penwright.plans[0].billing_cycles[1].price == Decimal("24.99")  # stale until reset

    new.reset()
    new.check_pricing()
    assert new.warnings == []
    penwright = next(mc for mc in new.load("merchants").items if mc.id == "penwright")
    assert penwright.plans[0].billing_cycles[1].price == Decimal("29.99")

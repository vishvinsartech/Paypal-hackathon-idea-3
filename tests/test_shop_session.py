"""Phase 7 Step 4: the shop stays public; the session decides Subscribe vs "Sign in to subscribe" (D-179)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

CHECKOUT_APIS = [
    ("/api/checkout/create", {"merchant_id": "penwright", "plan_key": "penwright-pro"}),
    ("/api/checkout/mock-approve", {"paypal_id": "I-NOPE"}),
    ("/api/subscriptions/register", {"paypal_id": "I-NOPE", "merchant_id": "penwright", "plan_key": "penwright-pro"}),
    ("/api/checkout/demo-paypal-window", {}),
]


@pytest.mark.parametrize(("url", "body"), CHECKOUT_APIS)
def test_signed_out_checkout_apis_return_401(anon_client: TestClient, url: str, body: dict[str, str]) -> None:
    res = anon_client.post(url, json=body)
    assert res.status_code == 401
    assert res.json()["rule_id"] == "AUTH"


@pytest.mark.parametrize("merchant", ["penwright", "quillnote"])
def test_signed_out_shop_links_to_sign_in(anon_client: TestClient, merchant: str) -> None:
    res = anon_client.get(f"/shop/{merchant}")
    assert res.status_code == 200
    html = res.text
    assert 'data-user=""' in html
    assert f'href="/login?next=/shop/{merchant}"' in html
    assert "Sign in to subscribe with SubGuard" in html
    assert 'data-testid="shop-paypal-btn"' not in html and "checkout.js" not in html and "companion.js" not in html
    assert 'data-testid="shop-signed-in"' not in html


def test_signed_in_shop_has_the_chip_and_session_user(client: TestClient) -> None:
    html = client.get("/shop/penwright").text
    assert 'data-user="priya"' in html
    assert "Signed in as Priya" in html
    assert 'data-testid="shop-paypal-btn"' in html and "shop-signin-subscribe" not in html


def test_shop_index_stays_public(anon_client: TestClient) -> None:
    assert anon_client.get("/shop").status_code == 200
    assert anon_client.get("/shop/penwright/terms").status_code == 200


def test_checkout_js_uses_the_session_user() -> None:
    from app.config import ROOT_DIR

    for name in ("checkout.js", "checkout_sandbox.js"):
        js = (ROOT_DIR / "shop" / "static" / name).read_text(encoding="utf-8")
        assert "document.body.dataset.user" in js
        assert 'get("user")' not in js and "/?user=" not in js

// Demo-shop checkout (mock mode): create -> approve -> register.
// The SubGuard companion (companion.js) reviews the page first; this runs only after "Continue to PayPal".
(function () {
  "use strict";
  const area = document.querySelector("[data-testid=shop-checkout]");
  const btn = area && area.querySelector("[data-mock-approve]");
  if (!btn) return;
  const user = new URLSearchParams(location.search).get("user") || "priya";
  const status = document.createElement("p");
  status.className = "checkout-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  area.appendChild(status);

  async function post(url, body) {
    const res = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || data.detail || ("HTTP " + res.status));
    return data;
  }

  async function subscribe(merchantId, planKey) {
    const created = await post("/api/checkout/create", {merchant_id: merchantId, plan_key: planKey, user_id: user});
    await post("/api/checkout/mock-approve", {paypal_id: created.paypal_id});
    return post("/api/subscriptions/register", {
      paypal_id: created.paypal_id, merchant_id: merchantId, plan_key: planKey, user_id: user,
      review_id: area.dataset.reviewId || null,
    });
  }

  async function checkout() {
    btn.disabled = true;
    status.textContent = "Mock PayPal approval…";
    try {
      const merchantId = area.dataset.merchant;
      const main = await subscribe(merchantId, area.dataset.planKey);
      const msg = "Subscribed. PayPal status: " + main.status + ".";
      status.innerHTML = "";
      status.append(msg + " ");
      const link = document.createElement("a");
      link.href = "/?user=" + encodeURIComponent(user);
      link.textContent = "Open SubGuard";
      link.dataset.testid = "shop-open-subguard";
      status.appendChild(link);
      const card = document.createElement("div");
      card.dataset.testid = "shop-paypal-card";
      area.appendChild(card);
      window.PayPalCard.mount(card, main.id, user);
    } catch (err) {
      status.textContent = "Checkout failed: " + err.message;
      btn.disabled = false;
    }
  }

  btn.addEventListener("click", checkout);
})();

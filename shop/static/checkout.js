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

  // U22: after approval the merchant page shows only its welcome, plus "Open SubGuard" in the companion strip.
  // The PayPal proof (ids, debug ids) lives on SubGuard's evidence page, not on someone else's site.
  function welcome(box, who) {
    const product = box.closest(".product") || box;
    const name = box.dataset.welcome || "us";
    product.innerHTML = `<div class="welcome" data-testid="shop-welcome" role="status">
      <h1 class="welcome-title">You're subscribed. Welcome to ${name.replace(/[<>&"]/g, "")}.</h1>
      <p class="companion-note" data-subguard-ignore>&#128737; SubGuard is watching this trial for you.
        <a href="/?user=${encodeURIComponent(who)}" target="_blank" rel="noopener" data-testid="shop-open-subguard">Open SubGuard ↗</a></p></div>`;
  }

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
    status.textContent = "PayPal approval (simulated)…";
    try {
      const merchantId = area.dataset.merchant;
      await subscribe(merchantId, area.dataset.planKey);
      welcome(area, user);
    } catch (err) {
      status.textContent = "Checkout failed: " + err.message;
      btn.disabled = false;
    }
  }

  btn.addEventListener("click", checkout);
  window.SGShopWelcome = welcome;
})();

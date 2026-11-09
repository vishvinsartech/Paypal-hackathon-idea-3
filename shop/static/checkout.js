// Demo-shop checkout (mock mode): create -> approve -> register, plus the add-on if it's ticked.
// Sandbox mode uses the real PayPal JS SDK button instead (wired up with the companion in milestone 4).
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

  async function subscribe(merchantId, planKey, addonOf) {
    const created = await post("/api/checkout/create", {merchant_id: merchantId, plan_key: planKey, user_id: user});
    await post("/api/checkout/mock-approve", {paypal_id: created.paypal_id});
    return post("/api/subscriptions/register", {
      paypal_id: created.paypal_id, merchant_id: merchantId, plan_key: planKey, user_id: user, addon_of: addonOf || null,
    });
  }

  async function checkout() {
    btn.disabled = true;
    status.textContent = "Talking to PayPal (sandbox mock)…";
    try {
      const merchantId = area.dataset.merchant;
      const main = await subscribe(merchantId, area.dataset.planKey, null);
      const addon = document.querySelector("[data-testid=shop-addon]");
      let msg = "Subscribed. PayPal status: " + main.status + ".";
      if (addon && addon.checked) {
        await subscribe(merchantId, addon.value, main.id);
        msg += " The add-on was added too.";
      }
      status.innerHTML = "";
      status.append(msg + " ");
      const link = document.createElement("a");
      link.href = "/?user=" + encodeURIComponent(user);
      link.textContent = "Open SubGuard";
      link.dataset.testid = "shop-open-subguard";
      status.appendChild(link);
    } catch (err) {
      status.textContent = "Checkout failed: " + err.message;
      btn.disabled = false;
    }
  }

  btn.addEventListener("click", checkout);
})();

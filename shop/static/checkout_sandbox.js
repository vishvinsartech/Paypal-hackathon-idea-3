// Demo-shop checkout (sandbox mode): the real PayPal JS SDK Subscribe button.
// It renders only after the SubGuard companion's "Continue to PayPal" (event `subguard:continue`).
(function () {
  "use strict";
  const area = document.querySelector("[data-testid=shop-checkout]");
  const slot = document.getElementById("paypal-area");
  if (!area || !slot) return;
  const user = new URLSearchParams(location.search).get("user") || "priya";
  const status = document.createElement("p");
  status.className = "checkout-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  area.appendChild(status);

  function loadSdk() {
    return new Promise((resolve, reject) => {
      if (window.paypal) return resolve(window.paypal);
      const s = document.createElement("script");
      s.src = "https://www.paypal.com/sdk/js?client-id=" + encodeURIComponent(area.dataset.clientId) +
        "&vault=true&intent=subscription";
      s.onload = () => resolve(window.paypal);
      s.onerror = () => reject(new Error("PayPal SDK failed to load"));
      document.head.appendChild(s);
    });
  }

  async function register(paypalId, planKey) {
    const res = await fetch("/api/subscriptions/register", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({paypal_id: paypalId, merchant_id: area.dataset.merchant, plan_key: planKey,
        user_id: user, review_id: area.dataset.reviewId || null}),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 202) throw new Error("PayPal hasn't activated it yet (status " + data.status + ")");
    if (!res.ok) throw new Error(data.error || data.detail || "HTTP " + res.status);
    return data;
  }

  function render(paypal, container, planId, planKey, onDone) {
    return paypal.Buttons({
      style: {shape: "pill", label: "subscribe"},
      createSubscription: (_data, actions) => actions.subscription.create({plan_id: planId}),
      onApprove: async (data) => {
        status.textContent = "Approved. Confirming with PayPal…";
        try {
          const sub = await register(data.subscriptionID, planKey);
          onDone(sub);
        } catch (err) {
          status.textContent = "Couldn't confirm the subscription: " + err.message;
        }
      },
      onCancel: () => { status.textContent = "You closed PayPal. Nothing was set up."; },
      onError: () => { status.textContent = "PayPal reported an error. Please try again."; },
    }).render(container);
  }

  window.addEventListener("subguard:continue", async () => {
    if (!area.dataset.planId) { status.textContent = "This plan isn't in the sandbox yet. Run `make seed`."; return; }
    try {
      const paypal = await loadSdk();
      slot.innerHTML = "";
      await render(paypal, slot, area.dataset.planId, area.dataset.planKey, () => done());
    } catch (err) {
      status.textContent = err.message;
    }
  });

  function done() {
    slot.innerHTML = "";
    status.innerHTML = "Subscribed. ";
    const link = document.createElement("a");
    link.href = "/?user=" + encodeURIComponent(user);
    link.textContent = "Open SubGuard";
    link.dataset.testid = "shop-open-subguard";
    status.appendChild(link);
  }
})();

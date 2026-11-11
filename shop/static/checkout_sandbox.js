// Demo-shop checkout (sandbox mode): the real PayPal JS SDK Subscribe button (D-113).
// It renders only after the SubGuard companion's "Continue to PayPal" (event `subguard:continue`). Our server
// creates the subscription (SDK + PayPal-Request-Id; PayPal deprecated client-side `actions.subscription`), and
// the button opens PayPal's own approval window for it. After approval the server confirms ACTIVE with PayPal.
(function () {
  "use strict";
  const area = document.querySelector("[data-testid=shop-checkout]");
  const slot = document.getElementById("paypal-area");
  if (!area || !slot) return;
  const user = new URLSearchParams(location.search).get("user") || "usera";
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
      createSubscription: async () => {
        status.textContent = "Opening PayPal…";
        const res = await fetch("/api/checkout/create", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({merchant_id: area.dataset.merchant, plan_key: planKey, user_id: user, js_sdk: true}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.paypal_id) throw new Error(data.error || "Couldn't start the PayPal subscription");
        return data.paypal_id;
      },
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

  // Live demo (D-117) and manual shop visits with the sandbox buyer in .env (D-120): a "Subscribe with PayPal"
  // button. Clicking it has the server open PayPal's approval page in its own window, already logged in as the
  // sandbox buyer; a person confirms there. A real PayPal pop-up can't be filled in from this page (other site).
  function demoButton() {
    slot.innerHTML = "";
    const b = document.createElement("button");
    b.type = "button";
    b.className = "paypal-btn";
    b.dataset.testid = "demo-subscribe";
    b.textContent = "Subscribe with PayPal";
    slot.appendChild(b);
    status.textContent = "Click Subscribe: PayPal opens logged in as the sandbox buyer, and you confirm there.";
    b.addEventListener("click", () => demoSubscribe(b));
    window.dispatchEvent(new CustomEvent("subguard:demo-ready"));
  }

  async function demoSubscribe(b) {
    b.disabled = true;
    status.textContent = "PayPal is open in a separate window, logged in as the sandbox buyer. Confirm the " +
      "subscription there…";
    window.dispatchEvent(new CustomEvent("subguard:demo-approving"));
    try {
      const res = await fetch("/api/checkout/demo-paypal-window", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({merchant_id: area.dataset.merchant, plan_key: area.dataset.planKey, user_id: user,
          review_id: area.dataset.reviewId || null, source: window.SG_AUTODEMO ? "demo" : "shop"}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || data.detail || "HTTP " + res.status);
      done(data);
      window.dispatchEvent(new CustomEvent("subguard:demo-subscribed", {detail: data}));
    } catch (err) {
      status.textContent = err.message + " Click Subscribe to try again.";
      b.disabled = false;
      window.dispatchEvent(new CustomEvent("subguard:demo-retry", {detail: err.message}));
    }
  }

  window.addEventListener("subguard:continue", async () => {
    if (!area.dataset.planId) {
      status.textContent = "This plan isn't in the sandbox yet. Run `make seed`.";
      window.dispatchEvent(new CustomEvent("subguard:demo-error", {detail: "No sandbox plan yet. Run make seed."}));
      return;
    }
    // Sandbox buyer in .env -> PayPal opens already logged in (no typing). Otherwise PayPal's own pop-up.
    if (window.SG_AUTODEMO || area.dataset.buyerLogin === "1") return demoButton();
    try {
      const paypal = await loadSdk();
      slot.innerHTML = "";
      await render(paypal, slot, area.dataset.planId, area.dataset.planKey, (sub) => done(sub));
    } catch (err) {
      status.textContent = err.message;
    }
  });

  function done(sub) {
    slot.innerHTML = "";
    status.innerHTML = "Subscribed. ";
    const link = document.createElement("a");
    link.href = "/?user=" + encodeURIComponent(user);
    link.textContent = "Open SubGuard";
    link.dataset.testid = "shop-open-subguard";
    status.appendChild(link);
    const card = document.createElement("div");
    card.dataset.testid = "shop-paypal-card";
    area.appendChild(card);
    window.PayPalCard.mount(card, sub.id, user);  // status re-read live from PayPal, not assumed
  }
})();

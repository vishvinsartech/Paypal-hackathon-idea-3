// Demo-shop checkout (sandbox mode, D-113/D-170). "Pay with PayPal (sandbox)" opens the SubGuard companion first;
// its "Continue to PayPal" (event `subguard:continue`) goes STRAIGHT to PayPal's confirmation, no second click:
//  - sandbox buyer in .env (D-117/D-120) or the live demo: the server opens PayPal's approval page logged in as the
//    sandbox buyer and a person confirms there; a "Subscribe with PayPal" button stays only to retry.
//  - otherwise: our server creates the subscription (SDK + PayPal-Request-Id) and this page goes to PayPal's approval
//    page; PayPal sends the buyer back to /shop/<merchant>?approved=1, where we confirm ACTIVE and register it.
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

  async function register(paypalId, planKey, who, reviewId) {
    const res = await fetch("/api/subscriptions/register", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({paypal_id: paypalId, merchant_id: area.dataset.merchant, plan_key: planKey,
        user_id: who || user, review_id: reviewId || area.dataset.reviewId || null}),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 202) throw new Error("PayPal hasn't activated it yet (status " + data.status + ")");
    if (!res.ok) throw new Error(data.error || data.detail || "HTTP " + res.status);
    return data;
  }

  // D-170: no second click. Create the subscription, remember it, and go to PayPal's own approval page.
  const PENDING = "sg-paypal-pending";
  async function redirectToPayPal() {
    status.textContent = "Taking you to PayPal to confirm…";
    try {
      const res = await fetch("/api/checkout/create", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({merchant_id: area.dataset.merchant, plan_key: area.dataset.planKey, user_id: user}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.approve_url) throw new Error(data.error || "Couldn't start the PayPal subscription");
      try {
        sessionStorage.setItem(PENDING, JSON.stringify({paypal_id: data.paypal_id, plan_key: area.dataset.planKey,
          user, review_id: area.dataset.reviewId || null}));
      } catch (e) { /* storage off: PayPal's return still carries subscription_id */ }
      location.assign(data.approve_url);
    } catch (err) {
      status.textContent = err.message + " Click Pay with PayPal to try again.";
    }
  }

  // Back from PayPal: ?approved=1&subscription_id=... (or ?cancelled=1).
  async function backFromPayPal() {
    const q = new URLSearchParams(location.search);
    let pending = {};
    try { pending = JSON.parse(sessionStorage.getItem(PENDING) || "{}"); } catch (e) { /* storage off */ }
    if (q.get("cancelled") === "1") {
      try { sessionStorage.removeItem(PENDING); } catch (e) { /* storage off */ }
      status.textContent = "You closed PayPal. Nothing was set up.";
      return;
    }
    if (q.get("approved") !== "1") return;
    const paypalId = q.get("subscription_id") || pending.paypal_id;
    if (!paypalId) { status.textContent = "PayPal sent you back without a subscription. Please try again."; return; }
    status.textContent = "Approved. Confirming with PayPal…";
    for (let i = 0; i < 10; i++) {  // PayPal can take a moment to show ACTIVE
      try {
        const sub = await register(paypalId, pending.plan_key || area.dataset.planKey, pending.user, pending.review_id);
        try { sessionStorage.removeItem(PENDING); } catch (e) { /* storage off */ }
        return done(sub, pending.user);
      } catch (err) {
        if (!/hasn't activated/.test(err.message) || i === 9) {
          status.textContent = "Couldn't confirm the subscription: " + err.message;
          return;
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
    }
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
    status.textContent = "PayPal opens logged in as the sandbox buyer; confirm there.";
    b.addEventListener("click", () => demoSubscribe(b));
    window.dispatchEvent(new CustomEvent("subguard:demo-ready"));
    return b;
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
    // Sandbox buyer in .env -> PayPal opens already logged in (no typing). Otherwise PayPal's own page.
    // Either way straight away: the shopper already clicked PayPal once (D-170).
    if (window.SG_AUTODEMO || area.dataset.buyerLogin === "1") return demoSubscribe(demoButton());
    return redirectToPayPal();
  });
  backFromPayPal();

  // U22: only the merchant's welcome + "Open SubGuard" here; PayPal ids live on SubGuard's evidence page.
  function done(sub, who) {
    const u = who || user;
    slot.innerHTML = "";
    const product = area.closest(".product") || area;
    const name = (area.dataset.welcome || "us").replace(/[<>&"]/g, "");
    product.innerHTML = `<div class="welcome" data-testid="shop-welcome" role="status" data-paypal-status="${String(sub.status || "").replace(/[^A-Z_]/g, "")}">
      <h1 class="welcome-title">You're subscribed. Welcome to ${name}.</h1>
      <p class="companion-note" data-subguard-ignore>&#128737; SubGuard is watching this trial for you.
        <a href="/?user=${encodeURIComponent(u)}" target="_blank" rel="noopener" data-testid="shop-open-subguard">Open SubGuard ↗</a></p></div>`;
  }
})();

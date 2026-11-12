// Demo-shop checkout (sandbox mode, D-113/D-170). "Pay with PayPal (sandbox)" opens the SubGuard companion first;
// its "Continue to PayPal" (event `subguard:continue`) goes STRAIGHT to PayPal's confirmation, no second click:
//  - sandbox buyer in .env (D-117/D-120) or the live demo: the server opens PayPal's approval page logged in as the
//    sandbox buyer and a person confirms there; a "Subscribe with PayPal" button stays only to retry.
//  - otherwise: our server creates the subscription (SDK + PayPal-Request-Id) and this page goes to PayPal's approval
//    page; PayPal sends the buyer back to /shop/<merchant>?approved=1, where we confirm ACTIVE and register it.
//  - the live demo on a server that can't approve for her (hosted, D-192, data-manual-approve): the PayPal JS SDK
//    button. A person logs in to PayPal and approves; onApprove posts the id to /register, which checks it with
//    PayPal. The window stays on this page, so the live demo hears about it and the window closes.
(function () {
  "use strict";
  const area = document.querySelector("[data-testid=shop-checkout]");
  const slot = document.getElementById("paypal-area");
  if (!area || !slot) return;
  const user = document.body.dataset.user || "";  // the session user, set by the server (Phase 7 Step 4)
  const status = document.createElement("p");
  status.className = "checkout-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  area.appendChild(status);

  async function register(paypalId, planKey, reviewId) {
    const res = await fetch("/api/subscriptions/register", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({paypal_id: paypalId, merchant_id: area.dataset.merchant, plan_key: planKey,
        user_id: user, review_id: reviewId || area.dataset.reviewId || null}),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 202) throw new Error("PayPal hasn't activated it yet (status " + data.status + ")");
    if (!res.ok) throw new Error(data.error || data.detail || "HTTP " + res.status);
    return data;
  }

  // PayPal can take a moment to show ACTIVE: retry while /register says "not yet" (202).
  async function registerWhenActive(paypalId, planKey, reviewId) {
    for (let i = 0; ; i++) {
      try {
        return await register(paypalId, planKey, reviewId);
      } catch (err) {
        if (!/hasn't activated/.test(err.message) || i === 9) throw err;
        await new Promise((r) => setTimeout(r, 1500));
      }
    }
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
          review_id: area.dataset.reviewId || null}));
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
    try {
      const sub = await registerWhenActive(paypalId, pending.plan_key || area.dataset.planKey, pending.review_id);
      try { sessionStorage.removeItem(PENDING); } catch (e) { /* storage off */ }
      return done(sub);
    } catch (err) {
      status.textContent = "Couldn't confirm the subscription: " + err.message;
    }
  }

  // ---- D-192: the hosted live demo. PayPal's own JS SDK button; a person logs in and approves. ----------------
  const TRY_AGAIN = " Click Subscribe with PayPal to try again.";
  const debugIdOf = (err) => {
    const m = /debug[_ ]?id["':=\s]+([A-Za-z0-9]+)/i.exec(String((err && (err.message || err)) || ""));
    return m ? m[1] : "";
  };
  let sdkLoading = null;
  function loadPayPalSdk() {
    if (window.paypal && window.paypal.Buttons) return Promise.resolve(window.paypal);
    if (sdkLoading) return sdkLoading;
    sdkLoading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://www.paypal.com/sdk/js?client-id=" + encodeURIComponent(area.dataset.clientId || "") +
        "&vault=true&intent=subscription&components=buttons";
      s.onload = () => (window.paypal && window.paypal.Buttons ? resolve(window.paypal)
        : reject(new Error("PayPal's button didn't load.")));
      s.onerror = () => { sdkLoading = null; reject(new Error("PayPal's button couldn't load (network).")); };
      document.head.appendChild(s);
    });
    return sdkLoading;
  }

  async function paypalButton() {
    slot.innerHTML = "";
    const box = document.createElement("div");
    box.id = "paypal-buttons";
    box.dataset.testid = "demo-subscribe";
    slot.appendChild(box);
    status.textContent = area.dataset.buyerCard === "1"
      ? "Click Subscribe with PayPal and log in with the sandbox buyer above."
      : "Click Subscribe with PayPal and log in with your PayPal sandbox buyer account.";
    let paypal;
    try {
      paypal = await loadPayPalSdk();
    } catch (err) {
      status.textContent = err.message + " Reload this window to try again.";
      window.dispatchEvent(new CustomEvent("subguard:demo-retry", {detail: err.message}));
      return;
    }
    const planKey = area.dataset.planKey;
    await paypal.Buttons({
      style: {label: "subscribe", layout: "vertical", shape: "rect"},
      onClick() {
        status.textContent = "PayPal is open. Log in with the sandbox buyer and approve the subscription there…";
        window.dispatchEvent(new CustomEvent("subguard:demo-approving"));
      },
      async createSubscription() {  // our server creates it (D-113): SDK + PayPal-Request-Id, plan from the seed
        const res = await fetch("/api/checkout/create", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({merchant_id: area.dataset.merchant, plan_key: planKey, user_id: user, js_sdk: true}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.paypal_id) {
          const msg = data.error || data.detail || "Couldn't start the PayPal subscription";
          throw new Error(data.debug_id ? `${msg} (debug_id ${data.debug_id})` : msg);
        }
        return data.paypal_id;
      },
      async onApprove(data) {
        status.textContent = "Approved. Confirming with PayPal…";
        try {
          const sub = await registerWhenActive(data.subscriptionID, planKey, area.dataset.reviewId);
          done(sub);
          window.dispatchEvent(new CustomEvent("subguard:demo-subscribed", {detail: sub}));
          if (!window.SG_AUTODEMO) closeNote();  // nothing will close this window by itself
        } catch (err) {
          status.textContent = "Couldn't confirm the subscription: " + err.message + TRY_AGAIN;
          window.dispatchEvent(new CustomEvent("subguard:demo-retry", {detail: err.message}));
        }
      },
      onCancel() {
        status.textContent = "You closed PayPal before approving." + TRY_AGAIN;
        window.dispatchEvent(new CustomEvent("subguard:demo-retry", {detail: "You closed PayPal before approving."}));
      },
      onError(err) {
        const id = debugIdOf(err);
        console.error("PayPal error" + (id ? " (debug_id " + id + ")" : ""), err);
        const what = String((err && err.message) || "").split("\n")[0].slice(0, 160) || "PayPal reported an error";
        status.textContent = "PayPal couldn't set up the subscription: " + what.replace(/\.$/, "") + "." + TRY_AGAIN;
        window.dispatchEvent(new CustomEvent("subguard:demo-retry",
          {detail: "PayPal couldn't set up the subscription" + (id ? " (debug_id " + id + ")" : "") + "."}));
      },
    }).render(box);
    window.dispatchEvent(new CustomEvent("subguard:demo-ready", {detail: {manual: true}}));
  }

  // window.close() can be refused (the window wasn't opened by a script): say so, with a Close button.
  function closeNote() {
    if (document.querySelector("[data-testid=shop-close-note]")) return;
    const p = document.createElement("p");
    p.className = "companion-note close-note";
    p.dataset.testid = "shop-close-note";
    p.setAttribute("data-subguard-ignore", "");
    p.setAttribute("role", "status");
    p.textContent = "Subscribed. You can close this window. ";
    const b = document.createElement("button");
    b.type = "button";
    b.className = "buyer-copy";
    b.textContent = "Close";
    b.addEventListener("click", () => window.close());
    p.appendChild(b);
    (document.querySelector("[data-testid=shop-welcome]") || document.body).appendChild(p);
  }
  window.addEventListener("subguard:close-blocked", closeNote);

  // The sandbox buyer card's Copy buttons (D-192).
  document.querySelectorAll(".buyer-copy[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    const el = document.querySelector(`[data-testid="${b.dataset.copy}"]`);
    if (!el) return;
    try {
      await navigator.clipboard.writeText(el.textContent.trim());
      b.textContent = "Copied";
    } catch (e) {
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      b.textContent = "Selected";
    }
    setTimeout(() => { b.textContent = "Copy"; }, 1500);
  }));

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
    // Either way straight away: the shopper already clicked PayPal once (D-170). Hosted live demo: PayPal's button.
    if (area.dataset.manualApprove === "1") return paypalButton();
    if (window.SG_AUTODEMO || area.dataset.buyerLogin === "1") return demoSubscribe(demoButton());
    return redirectToPayPal();
  });
  backFromPayPal();

  // U22: only the merchant's welcome + "Open SubGuard" here; PayPal ids live on SubGuard's evidence page.
  function done(sub) {
    slot.innerHTML = "";
    const product = area.closest(".product") || area;
    const name = (area.dataset.welcome || "us").replace(/[<>&"]/g, "");
    product.innerHTML = `<div class="welcome" data-testid="shop-welcome" role="status" data-paypal-status="${String(sub.status || "").replace(/[^A-Z_]/g, "")}">
      <h1 class="welcome-title">You're subscribed. Welcome to ${name}.</h1>
      <p class="companion-note" data-subguard-ignore>&#128737; SubGuard is watching this trial for you.
        <a href="/" target="_blank" rel="noopener" data-testid="shop-open-subguard">Open SubGuard ↗</a></p></div>`;
  }
})();

// Live demo, sandbox mode (D-116): this Penwright window was opened by the control room's Start button
// (?autodemo=1). It plays Priya's part: opens the Terms, clicks PayPal, lets the SubGuard companion's review
// stay on screen and clicks "Continue to PayPal", which opens PayPal straight away (D-168/D-170: the only step left
// to the presenter is confirming the order in PayPal's window), shows the welcome, tells the control room, closes.
// Hosted (D-192, data-manual-approve): PayPal's own button instead; the person logs in as the sandbox buyer shown
// above it and approves, then the same welcome, message and close follow.
(function () {
  "use strict";
  if (new URLSearchParams(location.search).get("autodemo") !== "1" || !window.opener) return;
  window.SG_AUTODEMO = true;
  const READ_MS = 6000;   // the companion's review stays up this long
  const CARD_MS = 5000;   // the "Subscribed via PayPal" card stays up this long before the window closes
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const tell = (msg) => {
    try { window.opener.postMessage({type: "subguard-demo", ...msg}, location.origin); } catch (e) { /* opener gone */ }
  };
  const banner = document.createElement("p");
  banner.className = "autodemo-banner";
  banner.setAttribute("role", "status");
  const checkout = document.querySelector("[data-testid=shop-checkout]");
  const manual = !!checkout && checkout.dataset.manualApprove === "1";
  banner.textContent = !manual
    ? "Live demo: this window plays Priya. Confirm the order in PayPal; this window then closes by itself."
    : checkout.dataset.buyerCard === "1"
      ? "Click Subscribe with PayPal and log in with the sandbox buyer above. This window closes after you approve."
      : "Click Subscribe with PayPal and log in with your PayPal sandbox buyer account. This window closes after you approve.";
  banner.style.cssText = "position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:10000;margin:0;" +
    "padding:8px 14px;border-radius:999px;background:#0f1f3a;color:#e8eef8;font:600 13px system-ui,sans-serif;" +
    "box-shadow:0 6px 20px rgba(0,0,0,.35)";

  window.addEventListener("subguard:review", async (ev) => {
    const r = ev.detail || {};
    tell({stage: "review", review: {review_id: r.review_id, risk_score: r.risk_score, summary: r.summary,
      deadlines: r.deadlines, display: r.display}});
    await sleep(READ_MS);
    const go = document.querySelector("[data-testid=companion-continue]");
    if (go) go.click();
  });
  window.addEventListener("subguard:review-error", (ev) => tell({stage: "error",
    message: "SubGuard couldn't check the Penwright page: " + ev.detail}));
  window.addEventListener("subguard:demo-ready", () => {
    window.focus();
    const b = document.querySelector("[data-testid=sandbox-buyer-card]") ||
      document.querySelector("[data-testid=demo-subscribe]");
    if (b) b.scrollIntoView({behavior: "smooth", block: "center"});
    tell(manual ? {stage: "ready", manual: true} : {stage: "ready"});  // checkout_sandbox.js opens PayPal right away (D-170); a person confirms the order
  });
  window.addEventListener("subguard:demo-approving", () => tell({stage: "approving"}));
  window.addEventListener("subguard:demo-retry", (ev) => tell({stage: "retry", message: ev.detail}));
  window.addEventListener("subguard:demo-error", (ev) => tell({stage: "error", message: ev.detail}));
  window.addEventListener("subguard:demo-subscribed", async (ev) => {
    window.focus();
    tell({stage: "subscribed", sub: ev.detail});
    await sleep(CARD_MS);
    try { window.opener.focus(); } catch (e) { /* the browser may not allow it */ }
    window.close();
    setTimeout(() => { if (!window.closed) window.dispatchEvent(new CustomEvent("subguard:close-blocked")); }, 600);
  });

  window.addEventListener("load", async () => {
    document.body.appendChild(banner);
    await sleep(1200);
    const terms = document.querySelector("[data-testid=shop-terms]");
    if (terms) { terms.open = true; terms.scrollIntoView({behavior: "smooth", block: "center"}); }
    await sleep(2500);
    const pay = document.querySelector("[data-testid=shop-paypal-btn]");
    pay.scrollIntoView({behavior: "smooth", block: "center"});
    await sleep(800);
    (pay.querySelector("button") || pay).click();  // the companion steps in before PayPal
    tell({stage: "reading"});
  });
})();

// Live demo, sandbox mode (D-116): this Penwright window was opened by the control room's Start button
// (?autodemo=1). It plays userA's part: opens the Terms, clicks PayPal, lets the SubGuard companion's review
// stay on screen, clicks "Continue to PayPal" (checkout_sandbox.js then has the server approve as the sandbox
// buyer), shows the live PayPal card, tells the control room, and closes itself.
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
  banner.textContent = "Live demo: this window plays userA. It closes by itself once you confirm in PayPal.";
  banner.style.cssText = "position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:10000;margin:0;" +
    "padding:8px 14px;border-radius:999px;background:#0f1f3a;color:#e8eef8;font:600 13px system-ui,sans-serif;" +
    "box-shadow:0 6px 20px rgba(0,0,0,.35)";

  window.addEventListener("subguard:review", async (ev) => {
    const r = ev.detail || {};
    tell({stage: "review", review: {review_id: r.review_id, risk_score: r.risk_score, summary: r.summary,
      deadlines: r.deadlines}});
    await sleep(READ_MS);
    const go = document.querySelector("[data-testid=companion-continue]");
    if (go) go.click();
  });
  window.addEventListener("subguard:review-error", (ev) => tell({stage: "error",
    message: "SubGuard couldn't check the Penwright page: " + ev.detail}));
  window.addEventListener("subguard:demo-ready", () => {
    window.focus();
    const b = document.querySelector("[data-testid=demo-subscribe]");
    if (b) b.scrollIntoView({behavior: "smooth", block: "center"});
    tell({stage: "ready"});
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

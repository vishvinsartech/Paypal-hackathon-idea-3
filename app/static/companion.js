// SubGuard companion: simulates the SubGuard browser extension on merchant checkouts (spec 5.5).
// It steps in when the shopper clicks the PayPal area, reviews the page via /api/review/preflight, and only
// "Continue to PayPal" lets the PayPal approval go ahead. On failure/timeout it never blocks silently.
(function () {
  "use strict";
  const area = document.querySelector("[data-testid=shop-paypal-btn]");
  const checkout = document.querySelector("[data-testid=shop-checkout]");
  if (!area || !checkout) return;
  const user = new URLSearchParams(location.search).get("user") || "priya";
  const TIMEOUT_MS = 20000;
  let cleared = false;
  let overlay = null;
  let lastFocus = null;

  const css = `
  .sg-backdrop{position:fixed;inset:0;background:rgba(6,16,33,.62);display:flex;align-items:center;justify-content:center;z-index:9999;padding:16px}
  .sg-card{background:#0f1f3a;color:#e8eef8;font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;border-radius:16px;max-width:560px;width:100%;max-height:min(720px,90vh);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.45);border:1px solid #23406b}
  .sg-head{display:flex;gap:12px;align-items:center;padding:16px 20px;border-bottom:1px solid #23406b;flex:none}
  .sg-head img{width:28px;height:28px}.sg-head h2{font-size:17px;margin:0;flex:1}.sg-head h2:focus{outline:none}
  .sg-card>.sg-body{flex:1 1 auto;overflow-y:auto;overscroll-behavior:contain}
  .sg-consent{display:flex;gap:8px;align-items:flex-start;font-size:14px;margin:10px 0 4px;padding:8px 10px;border:1px solid #23406b;border-radius:8px}
  .sg-consent input{margin-top:3px;width:16px;height:16px;accent-color:#1fb59a}
  .sg-risk{font-weight:800;font-size:15px;padding:4px 10px;border-radius:999px;background:#7a1f2b;color:#fff}
  .sg-risk.low{background:#0f6b5c}.sg-risk.mid{background:#8a5a00}
  .sg-body{padding:14px 20px}.sg-body ul{padding-left:18px;margin:6px 0 10px}.sg-body li{margin:6px 0}
  .sg-q{display:block;color:#9fb3d1;font-size:12.5px;font-style:italic;margin-top:2px}
  .sg-deadline{background:#16294a;border-left:4px solid #e05260;padding:8px 12px;border-radius:6px;margin:8px 0}
  .sg-deadline.ok{border-left-color:#1fb59a}
  .sg-table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}.sg-table td,.sg-table th{padding:4px 6px;border-bottom:1px solid #23406b;text-align:left}
  .sg-bad{color:#ff8a95}.sg-good{color:#5fe0c4}.sg-mode{font-size:12px;color:#9fb3d1}
  .sg-actions{display:flex;gap:10px;justify-content:flex-end;padding:14px 20px;border-top:1px solid #23406b;flex:none}
  .sg-btn{border:0;border-radius:10px;padding:10px 16px;font:600 15px system-ui,sans-serif;cursor:pointer}
  .sg-btn:focus-visible{outline:3px solid #5fe0c4;outline-offset:2px}
  .sg-back{background:#e8eef8;color:#0f1f3a}.sg-go{background:#1fb59a;color:#06231d}
  .sg-spin{display:inline-block;width:18px;height:18px;border:3px solid #23406b;border-top-color:#1fb59a;border-radius:50%;animation:sg-r 0.8s linear infinite;vertical-align:middle;margin-right:8px}
  @keyframes sg-r{to{transform:rotate(360deg)}}`;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  function open(inner) {
    close();
    lastFocus = document.activeElement;
    overlay = document.createElement("div");
    overlay.className = "sg-backdrop";
    overlay.setAttribute("data-subguard-ignore", "");
    overlay.innerHTML = `<div class="sg-card" role="dialog" aria-modal="true" aria-labelledby="sg-title" data-testid="companion-overlay">${inner}</div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("keydown", onKey);
    // B1: focus the title, not the first button, so opening never scrolls the card away from the risk badge
    const title = overlay.querySelector("#sg-title");
    title.setAttribute("tabindex", "-1");
    title.focus({preventScroll: true});
    overlay.querySelectorAll(".sg-card, .sg-body").forEach((el) => { el.scrollTop = 0; });
  }

  function onKey(e) {
    if (e.key === "Escape") { backOut(); return; }
    if (e.key !== "Tab") return;  // keep focus inside the dialog
    const items = [...overlay.querySelectorAll("button, input, summary, a[href]")].filter((el) => !el.disabled);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement.id === "sg-title")) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  }

  function close() {
    if (overlay) overlay.remove();
    overlay = null;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  const head = (extra) => `<div class="sg-head"><img src="/static/shield.svg" alt=""><h2 id="sg-title">SubGuard checked this offer</h2>${extra || ""}</div>`;

  function renderLoading() {
    open(`${head()}<div class="sg-body" role="status" aria-live="polite" data-testid="companion-loading"><span class="sg-spin"></span>Reading the fine print and checking the PayPal plan…</div>`);
  }

  function renderError(msg) {
    open(`${head()}<div class="sg-body" role="alert" data-testid="companion-error"><p>SubGuard couldn't check this page. Continue at your own risk?</p><p class="sg-mode">${esc(msg)}</p></div>
      <div class="sg-actions"><button class="sg-btn sg-back" data-testid="companion-back">Back out</button><button class="sg-btn sg-go" data-testid="companion-continue">Continue to PayPal</button></div>`);
    wire(null);
    window.dispatchEvent(new CustomEvent("subguard:review-error", {detail: msg}));
  }

  function renderReview(r) {
    const level = r.risk_score >= 60 ? "" : r.risk_score >= 30 ? "mid" : "low";
    const d = r.deadlines;
    const show = r.display || {};  // B2: built by the server, relative to sign-up, never sim days
    const trap = show.trap ?? (d.real_cancel_deadline_day < d.first_charge_day - 1);
    const items = r.clauses.map((c) => `<li data-testid="finding-${esc(c.type)}">${esc(c.plain_english)}<span class="sg-q">“${esc(c.quote.length > 160 ? c.quote.slice(0, 157) + "…" : c.quote)}”</span></li>`).join("");
    const rows = r.paypal_check.map((row) => `<tr><td>${esc(row.item)}</td><td>${esc(row.page_says)}</td><td>${esc(row.paypal_says)}</td><td class="${row.match ? "sg-good" : "sg-bad"}">${row.match ? "✓" : "✗"}</td></tr>`).join("");
    const deadline = trap
      ? `<div class="sg-deadline" data-testid="companion-deadline"><strong data-testid="companion-act-by">${esc(show.act_by_text)}</strong>, ${esc(show.points.act_by.relative)}. That's before the trial ends (${esc(show.points.trial_end.date)}); the first charge is ${esc(show.points.first_charge.date)}.</div>`
      : `<div class="sg-deadline ok" data-testid="companion-deadline">${esc(show.deadline_text)} ${r.risk_score < 30 ? "Terms look clear." : ""}</div>`;
    const consent = trap && d.auto_timer_allowed
      ? `<label class="sg-consent"><input type="checkbox" data-testid="companion-auto-send"> <span>If I don't answer, send the cancellation email for me.</span></label>` : "";
    open(`${head(`<span class="sg-risk ${level}" data-testid="companion-risk" aria-label="Risk ${r.risk_score} out of 100">Risk ${r.risk_score}/100</span>`)}
      <div class="sg-body">
        <p class="sg-mode">${esc(r.mode_label)} · ${esc(r.provider)}${r.injection_flagged ? " · hidden instructions to AI were found and ignored" : ""}</p>
        ${r.summary ? `<p data-testid="companion-summary">${esc(r.summary)}</p>` : ""}
        ${deadline}
        ${trap && d.auto_timer_allowed ?`<p data-testid="companion-promise"><strong>I'll check with you before your trial runs out.</strong></p>` : ""}
        <ul>${items}</ul>
        <p><strong>PayPal cross-check</strong> (PayPal is the source of truth)</p>
        <table class="sg-table"><thead><tr><th>Check</th><th>Page</th><th>PayPal plan</th><th></th></tr></thead><tbody>${rows}</tbody></table>
        ${consent}
      </div>
      <div class="sg-actions"><button class="sg-btn sg-back" data-testid="companion-back">Back out</button><button class="sg-btn sg-go" data-testid="companion-continue">Continue to PayPal</button></div>`);
    wire(r.review_id);
    window.dispatchEvent(new CustomEvent("subguard:review", {detail: r}));  // the live demo's Penwright window listens
  }

  function backOut() {
    close();
  }

  function wire(reviewId) {
    overlay.querySelector("[data-testid=companion-back]").addEventListener("click", backOut);
    overlay.querySelector("[data-testid=companion-continue]").addEventListener("click", () => proceed(reviewId));
  }

  async function saveConsent(reviewId) {  // D7: saved on the review; sign-up copies it to the consent snapshot
    const box = overlay && overlay.querySelector("[data-testid=companion-auto-send]");
    if (!reviewId || !box) return;
    try {
      await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/consent`, {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: user, auto_send_notice: box.checked})});
    } catch (err) { /* the sign-up still goes ahead; the box just stays unticked */ }
  }

  async function proceed(reviewId) {
    cleared = true;
    if (reviewId) checkout.dataset.reviewId = reviewId;
    await saveConsent(reviewId);
    close();
    window.dispatchEvent(new CustomEvent("subguard:continue", {detail: {reviewId}}));
    const mockBtn = area.querySelector("[data-mock-approve]");
    if (mockBtn) mockBtn.click();
  }

  async function preflight() {
    renderLoading();
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    try {
      const res = await fetch("/api/review/preflight", {
        method: "POST", headers: {"Content-Type": "application/json"}, signal: ctrl.signal,
        body: JSON.stringify({merchant_url: location.origin + location.pathname, plan_key: checkout.dataset.planKey, user_id: user}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "HTTP " + res.status);
      renderReview(data);
    } catch (err) {
      renderError(err.name === "AbortError" ? "The check took longer than 20 seconds." : err.message);
    } finally {
      clearTimeout(timer);
    }
  }

  // Capture phase on the PayPal area: runs before the shop's own button handler.
  area.addEventListener("click", (ev) => {
    if (cleared) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    preflight();
  }, true);
})();

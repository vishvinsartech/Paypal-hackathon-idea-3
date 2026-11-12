// SubGuard companion: simulates the SubGuard browser extension on merchant checkouts (spec 5.5).
// It steps in when the shopper clicks the PayPal area, reviews the page via /api/review/preflight, and only
// "Continue to PayPal" lets the PayPal approval go ahead. On failure/timeout it never blocks silently.
// U14/D-170 order: title ("is checking" -> "checked") -> What you'll pay -> Key dates -> Watch out for ->
// PayPal check -> consent box -> Back out / Continue. In sandbox, Continue goes straight to PayPal.
// U15: the evidence (every quote once, plain English first) and the cross-check table are folded away.
// U17: max 720 px, scrolling middle, sticky head + foot; a bottom sheet at <= 640 px. U28: focus trap + Esc.
(function () {
  "use strict";
  const area = document.querySelector("[data-testid=shop-paypal-btn]");
  const checkout = document.querySelector("[data-testid=shop-checkout]");
  if (!area || !checkout) return;
  const user = new URLSearchParams(location.search).get("user") || "priya";
  // D-119: longer than the server's own worst case (page capture + LLM_TIMEOUT_SECONDS, 30 s by default, shared by
  // both LLM attempts). The server answers inside that budget, falling back to the basic check if the AI is slow.
  const TIMEOUT_MS = 50000;
  let cleared = false;
  let overlay = null;
  let lastFocus = null;

  const css = `
  .sg-backdrop{position:fixed;inset:0;background:rgba(6,16,33,.62);display:flex;align-items:center;justify-content:center;z-index:9999;padding:16px}
  .sg-card{--sg-bg:#0f1f3a;--sg-text:#e8eef8;--sg-surface:#16294a;--sg-line:#23406b;--sg-muted:#a9bbd6;--sg-red:#ff8a95;--sg-teal:#1fb59a;--sg-accent:#5fe0c4;--sg-link:#7fe3cf;--sg-chip-line:#3a5b8c;--sg-chip:#c9d6ea;--sg-amber:#f5b942;--sg-back-bg:#e8eef8;--sg-back:#0f1f3a;--sg-shadow:rgba(0,0,0,.45);background:var(--sg-bg);color:var(--sg-text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;border-radius:16px;max-width:540px;width:100%;max-height:min(720px,90vh);box-sizing:border-box;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 18px 50px var(--sg-shadow);border:1px solid var(--sg-line)}
  .sg-backdrop.sg-light{background:rgba(16,32,54,.35)}
  .sg-light .sg-card{--sg-bg:#ffffff;--sg-text:#102036;--sg-surface:#f1f5fa;--sg-line:#d3dde9;--sg-muted:#52627a;--sg-red:#c8323a;--sg-teal:#0b7f76;--sg-accent:#0b7f76;--sg-link:#0b7f76;--sg-chip-line:#c8d4e3;--sg-chip:#33445c;--sg-amber:#b07800;--sg-back-bg:#e7edf5;--sg-back:#102036;--sg-shadow:rgba(16,32,54,.22)}
  .sg-light .sg-head img{filter:none}.sg-light .sg-go{color:#fff}.sg-light .sg-date.key{background:rgba(200,50,58,.08)}
  .sg-card *{box-sizing:border-box}
  .sg-head{display:flex;gap:12px;align-items:center;padding:14px 20px;border-bottom:1px solid var(--sg-line);flex:none}
  .sg-head img{width:26px;height:26px}.sg-head h2{font-size:16px;font-weight:700;margin:0;flex:1}.sg-head h2:focus{outline:none}
  .sg-card>.sg-body{flex:1 1 auto;overflow-y:auto;overscroll-behavior:contain}
  .sg-risk{font-weight:700;font-size:14px;padding:3px 10px;border-radius:999px;background:#b3313a;color:#fff;white-space:nowrap}
  .sg-risk.low{background:#0f6b5c}.sg-risk.mid{background:#8a5a00}
  .sg-body{padding:16px 20px;display:grid;gap:16px}.sg-body p{margin:0}
  .sg-sec{display:grid;gap:6px}
  .sg-label{font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--sg-muted);margin:0}
  .sg-verdict{font-size:19px;font-weight:700;line-height:1.3}
  .sg-sub{color:var(--sg-muted);font-size:14px}
  .sg-dates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0;padding:0;list-style:none}
  .sg-date{background:var(--sg-surface);border-radius:10px;padding:8px 10px;display:grid;gap:1px}
  .sg-date span{font-size:12px;color:var(--sg-muted)}.sg-date strong{font-size:15px;font-weight:700}
  .sg-date.key{background:rgba(255,90,95,.14)}.sg-date.key strong{color:var(--sg-red)}
  .sg-date small{font-size:11.5px;color:var(--sg-muted)}
  .sg-promise{font-size:13.5px;color:var(--sg-muted)}
  .sg-things{list-style:none;padding:0;margin:0;display:grid;gap:8px}
  .sg-things li{display:grid;grid-template-columns:14px minmax(0,1fr);gap:8px;font-size:14px}
  .sg-things li::before{content:"";width:8px;height:8px;border-radius:50%;margin-top:7px;background:var(--sg-muted)}
  .sg-things li.high::before{background:var(--sg-red)}.sg-things li.mid::before{background:var(--sg-amber)}
  .sg-things b{font-weight:700}.sg-things .sg-t{color:var(--sg-muted)}
  .sg-check{display:grid;grid-template-columns:20px minmax(0,1fr);gap:8px;font-size:14px;padding:10px 12px;border-radius:10px;background:var(--sg-surface)}
  .sg-check .sg-ico{font-weight:700;color:var(--sg-teal)}.sg-check.warn .sg-ico{color:var(--sg-red)}
  .sg-shield{font-size:12.5px;color:var(--sg-muted)}
  .sg-consent{display:flex;gap:10px;align-items:flex-start;font-size:14px}
  .sg-consent input{margin-top:3px;width:16px;height:16px;accent-color:var(--sg-teal);flex:none}
  .sg-evidence>summary{cursor:pointer;color:var(--sg-link);font-weight:600;font-size:14px}
  .sg-evidence>summary:focus-visible{outline:3px solid var(--sg-accent);outline-offset:2px}
  .sg-summary{color:var(--sg-muted);font-size:13.5px;margin:8px 0!important}
  .sg-quotes{padding-left:18px;margin:8px 0;font-size:14px}.sg-quotes li{margin:8px 0}
  .sg-chip{display:inline-block;font-size:11.5px;font-weight:700;padding:1px 8px;border-radius:999px;border:1px solid var(--sg-chip-line);color:var(--sg-chip);margin-left:4px;vertical-align:1px}
  .sg-q{display:block;color:var(--sg-muted);font-size:12.5px;font-style:italic;margin-top:2px}
  .sg-h3{font-size:13px;font-weight:700;margin:12px 0 4px!important}
  .sg-table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}.sg-table td{padding:5px 6px;border-bottom:1px solid var(--sg-line);text-align:left}
  .sg-fail td{background:rgba(255,90,95,.12)}.sg-card .sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
  .sg-bad{color:var(--sg-red);font-weight:700}.sg-good{color:var(--sg-accent);font-weight:700}.sg-mode{font-size:12px;color:var(--sg-muted)}
  .sg-actions{display:flex;gap:10px;justify-content:flex-end;padding:12px 20px;border-top:1px solid var(--sg-line);flex:none}
  .sg-btn{border:0;border-radius:10px;padding:10px 18px;font:600 15px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;cursor:pointer}
  .sg-btn:focus-visible{outline:3px solid var(--sg-accent);outline-offset:2px}
  .sg-back{background:var(--sg-back-bg);color:var(--sg-back)}.sg-go{background:var(--sg-teal);color:#06231d}
  .sg-loading{display:flex;align-items:center;gap:10px;color:var(--sg-muted)}
  .sg-spin{display:inline-block;width:18px;height:18px;border:3px solid var(--sg-line);border-top-color:var(--sg-teal);border-radius:50%;animation:sg-r 0.8s linear infinite;flex:none}
  @keyframes sg-r{to{transform:rotate(360deg)}}
  @keyframes sg-up{from{transform:translateY(40px);opacity:0}to{transform:none;opacity:1}}
  @media (max-width:640px){.sg-backdrop{align-items:flex-end;padding:0}
    .sg-card{max-width:none;border-radius:16px 16px 0 0;max-height:min(720px,88vh);animation:sg-up .25s ease-out}
    .sg-verdict{font-size:17px}.sg-actions{padding:10px 16px}.sg-actions .sg-btn{flex:1}.sg-body{padding:14px 16px}.sg-head{padding:12px 16px}
    .sg-date{padding:7px 8px}.sg-date strong{font-size:14px}}
  @media (prefers-reduced-motion:reduce){.sg-card,.sg-spin{animation:none}}`;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  // The card follows the theme picked in SubGuard (the same "sg-theme" key as app.js; the shop is the same origin).
  function theme() {
    const t = document.documentElement.getAttribute("data-theme");
    if (t) return t;
    try { return localStorage.getItem("sg-theme") || "dark"; } catch (e) { return "dark"; }
  }
  window.addEventListener("storage", (e) => {
    if (e.key === "sg-theme" && overlay) overlay.classList.toggle("sg-light", e.newValue === "light");
  });

  function open(inner) {
    close();
    lastFocus = document.activeElement;
    overlay = document.createElement("div");
    overlay.className = "sg-backdrop" + (theme() === "light" ? " sg-light" : "");
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
    const items = [...overlay.querySelectorAll("button, input, summary, a[href]")].filter((el) => !el.disabled && el.offsetParent !== null);
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

  // The title says what is happening: "checking" while the review runs, "checked" only once it's done (D-170).
  const head = (title, extra) => `<div class="sg-head"><img src="/static/shield.svg" alt=""><h2 id="sg-title" data-testid="companion-title">${title}</h2>${extra || ""}</div>`;

  function renderLoading() {
    open(`${head("SubGuard is checking this offer…")}<div class="sg-body" role="status" aria-live="polite" data-testid="companion-loading"><p class="sg-loading"><span class="sg-spin"></span>Reading the fine print and checking the PayPal plan…</p></div>`);
  }

  function renderError(msg) {
    open(`${head("SubGuard couldn't check this offer")}<div class="sg-body" role="alert" data-testid="companion-error"><p>SubGuard couldn't check this page. Continue at your own risk?</p><p class="sg-mode">${esc(msg)}</p></div>
      <div class="sg-actions"><button class="sg-btn sg-back" data-testid="companion-back">Back out</button><button class="sg-btn sg-go" data-testid="companion-continue">Continue to PayPal</button></div>`);
    wire(null);
    window.dispatchEvent(new CustomEvent("subguard:review-error", {detail: msg}));
  }

  // U14, D-170: four plain sections (What you'll pay, Key dates, Watch out for, PayPal check), then the consent box
  // and the folded evidence. The act-by date is the only red.
  function renderReview(r) {
    const level = r.risk_score >= 60 ? "" : r.risk_score >= 30 ? "mid" : "low";
    const d = r.deadlines;
    const show = r.display || {};  // B2: built by the server, relative to sign-up, never sim days
    const v = show.verdict || {things: [], quotes: [], rows: []};
    const pts = show.points || {};
    const trap = show.trap ?? (d.real_cancel_deadline_day < d.first_charge_day - 1);
    const sev = (n) => (n >= 5 ? "high" : n >= 4 ? "mid" : "low");
    const things = v.things.map((t) => `<li class="${sev(t.severity)}" data-testid="finding-${esc(t.type)}"><span><b>${esc(t.label)}.</b> <span class="sg-t">${esc(t.text)}</span></span></li>`).join("");
    const quotes = v.quotes.map((q) => `<li data-testid="evidence-${esc(q.type)}">${esc(q.text)} <span class="sg-chip">${esc(q.label)}</span><span class="sg-q">“${esc(q.quote.length > 180 ? q.quote.slice(0, 177) + "…" : q.quote)}”</span></li>`).join("");
    const rows = v.rows.map((row) => `<tr class="${row.match ? "" : "sg-fail"}"><td>${esc(row.label)}</td><td class="${row.match ? "sg-good" : "sg-bad"}"><span aria-hidden="true">${row.match ? "✓" : "✗"}</span><span class="sr-only">${row.match ? "matches" : "doesn't match"}</span></td></tr>`).join("");
    const mismatch = r.clauses.some((c) => c.type === "TERMS_MISMATCH");
    const date = (key, label, extra, cls) => pts[key] ? `<li class="sg-date${cls ? " " + cls : ""}" data-testid="companion-date-${key}"><span>${label}</span><strong>${esc(pts[key].date)}</strong>${extra ? `<small>${extra}</small>` : ""}</li>` : "";
    const dates = trap && pts.act_by
      ? `<section class="sg-sec" data-testid="companion-deadline"><p class="sg-label">Key dates</p>
          <ul class="sg-dates">${date("act_by", "Act by", pts.terms_last ? `terms allow ${esc(pts.terms_last.date)}` : "", "key")}${date("trial_end", "Trial ends")}${date("first_charge", "First charge")}</ul>
          ${d.auto_timer_allowed ? `<p class="sg-promise" data-testid="companion-promise">I'll check with you before your trial runs out.</p>` : ""}</section>`
      : `<section class="sg-sec" data-testid="companion-deadline"><p class="sg-label">Key dates</p><p>${esc(show.deadline_text)}${r.risk_score < 30 ? " Terms look clear." : ""}</p></section>`;
    const check = v.paypal_line ? `<section class="sg-sec"><p class="sg-label">PayPal check</p>
        <p class="sg-check${v.paypal_warn ? " warn" : ""}" data-testid="${mismatch ? "finding-TERMS_MISMATCH" : "companion-paypal-check"}"><span class="sg-ico" aria-hidden="true">${v.paypal_warn ? "✗" : "✓"}</span><span>${esc(v.paypal_line)}</span></p></section>` : "";
    const consent = trap && d.auto_timer_allowed
      ? `<label class="sg-consent"><input type="checkbox" data-testid="companion-auto-send"${r.auto_send_default ? " checked" : ""}> <span>If I don't answer, send the cancellation email for me.</span></label>` : "";
    open(`${head("SubGuard checked this offer", `<span class="sg-risk ${level}" data-testid="companion-risk" aria-label="Risk ${r.risk_score} out of 100">Risk ${r.risk_score}/100</span>`)}
      <div class="sg-body">
        <section class="sg-sec"><p class="sg-label">What you'll pay</p>
          <p class="sg-verdict" data-testid="companion-verdict">${esc(v.line || r.summary)}</p>
          ${v.sub ? `<p class="sg-sub" data-testid="companion-verdict-sub">${esc(v.sub)}</p>` : ""}</section>
        ${dates}
        ${things ? `<section class="sg-sec"><p class="sg-label">Watch out for</p><ul class="sg-things" data-testid="companion-things">${things}</ul></section>` : ""}
        ${check}
        ${r.injection_flagged ? `<p class="sg-shield" data-testid="finding-PROMPT_INJECTION_ATTEMPT"><span aria-hidden="true">&#128737;</span> Hidden instructions to AI found on this page and ignored.</p>` : ""}
        ${consent}
        <details class="sg-evidence" data-testid="companion-evidence"><summary>Show evidence (${esc(v.evidence_label || "quoted clauses")})</summary>
          ${r.summary ? `<p class="sg-summary" data-testid="companion-summary">${esc(r.summary)}</p>` : ""}
          <ul class="sg-quotes">${quotes}</ul>
          <p class="sg-h3">Page vs PayPal plan <span class="sg-mode">(PayPal is the source of truth)</span></p>
          <table class="sg-table"><tbody>${rows}</tbody></table>
          <p class="sg-mode">${esc(r.mode_label)}${r.provider === "mock" ? "" : ` · ${esc(r.model)}`}</p>
        </details>
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
      renderError(err.name === "AbortError" ? `The check took longer than ${TIMEOUT_MS / 1000} seconds.` : err.message);
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

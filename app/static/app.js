// SubGuard shared UI helpers (window.SG): API calls, toasts, the confirmation card, health dots.
(function () {
  "use strict";
  const user = document.body.dataset.user || "priya";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const listeners = [];

  async function api(path, opts) {
    const init = Object.assign({headers: {"Content-Type": "application/json"}}, opts || {});
    if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
    const res = await fetch(path, init);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.reason ? `Blocked (${data.rule_id}): ${data.reason}` : (data.error || data.detail || `Request failed (${res.status})`);
      const err = new Error(typeof msg === "string" ? msg : "Request failed");
      err.data = data;
      throw err;
    }
    return data;
  }

  function toast(text, opts) {
    const box = document.getElementById("toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = "toast toast-" + ((opts && opts.level) || "info");
    el.dataset.testid = (opts && opts.testid) || "toast";
    el.setAttribute("role", (opts && opts.level === "urgent") ? "alert" : "status");
    el.innerHTML = (opts && opts.title ? `<strong>${esc(opts.title)}</strong><br>` : "") + esc(text);
    const close = document.createElement("button");
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "✕";
    close.addEventListener("click", () => el.remove());
    el.appendChild(close);
    box.appendChild(el);
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => el.remove(), (opts && opts.ms) || 6000);  // B5: auto-dismiss after 6 s
  }

  // ---- refresh fan-out: panels register, actions call SG.refresh() ------------------------
  function onRefresh(fn) { listeners.push(fn); }
  async function refresh() {
    await Promise.all(listeners.map((fn) => Promise.resolve().then(fn).catch((e) => console.warn("refresh", e.message))));
  }

  // ---- confirmation card (chat + alerts + grid) ----------------------------------------------
  function cardHtml(card) {
    const rows = card.items.map((i) => `<li><strong>${esc(i.merchant)}</strong> · ${esc(i.plan)} <span class="money">${esc(i.per_year_text)}</span></li>`).join("");
    return `<div class="confirm-card" data-testid="confirm-card" role="group" aria-label="Confirm cancellation">
      <h3 id="confirm-title">Cancel ${card.items.length === 1 ? esc(card.items[0].merchant) : card.items.length + " subscriptions"}?</h3>
      <ul class="plain">${rows}</ul>
      <p>Money at stake: <strong class="money" data-testid="confirm-total">${esc(card.total_text)}</strong></p>
      <p class="muted small">${esc(card.reason)}</p>
      <p class="warn small">${esc(card.warning)}</p>
      <div class="row"><button class="btn btn-danger" data-testid="confirm-button">Confirm cancel</button>
      <button class="btn btn-ghost" data-role="dismiss">Not now</button></div></div>`;
  }

  // Renders the card into `host`; resolves with the /api/agent/confirm result, or null if dismissed.
  function showCard(card, host) {
    host.innerHTML = cardHtml(card);
    return new Promise((resolve) => {
      const btn = host.querySelector("[data-testid=confirm-button]");
      host.querySelector("[data-role=dismiss]").addEventListener("click", () => { host.innerHTML = ""; resolve(null); });
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "Cancelling…";
        try {
          const out = await api("/api/agent/confirm", {method: "POST", body: {user_id: user, token: card.token, subscription_ids: card.items.map((i) => i.subscription_id)}});
          resolve(out);
        } catch (err) {
          resolve({error: err.message, results: []});
        }
      });
    });
  }

  function resultLines(out) {
    if (out.error) return [{ok: false, text: out.error}];
    return out.results.map((r) => ({ok: r.ok || r.outcome === "action_needed", text: (r.ok ? "✓ " : r.outcome === "action_needed" ? "→ " : "✗ ") + r.message, transport: r.transport, outcome: r.outcome}));
  }

  // Modal variant used by alerts and the grid's Cancel button.
  async function confirmInDialog(card) {
    const dlg = document.getElementById("confirm-dialog");
    if (!dlg) return null;
    dlg.innerHTML = "";
    const host = document.createElement("div");
    dlg.appendChild(host);
    dlg.showModal();
    const out = await showCard(card, host);
    dlg.close();
    if (out) {
      // Success goes straight to the email preview (no extra pop-up); only problems are toasted.
      resultLines(out).filter((l) => !l.ok || !(out.results || []).some((r) => r.notice_id))
        .forEach((l) => toast(l.text, {level: l.ok ? "info" : "urgent", testid: "toast-result"}));
      await refresh();
      await openDrafts(out);
    }
    return out;
  }

  // PayPal cancelled first; now show each cancellation email draft for Priya to review and send (D-104).
  async function openDrafts(out) {
    for (const r of (out && out.results) || []) {
      // Layer 2 (A5): no PayPal cancel happened, so don't say "Cancelled in PayPal"
      if (r.notice_id && window.SG.openEmail) await window.SG.openEmail(r.notice_id, {justCancelled: r.ok});
    }
  }

  async function proposeCancel(subIds, reason) {
    try {
      const card = await api("/api/agent/propose", {method: "POST", body: {user_id: user, subscription_ids: subIds, reason: reason || "Cancelled from the dashboard"}});
      return confirmInDialog(card);
    } catch (err) {
      toast(err.message, {level: "urgent"});
      return null;
    }
  }

  async function loadHealth() {
    const el = document.getElementById("health");
    if (!el) return;
    try {
      const data = await api("/healthz");
      el.innerHTML = "";
      for (const [name, info] of Object.entries(data.integrations)) {
        const dot = document.createElement("span");
        dot.className = "dot " + info.state;
        dot.title = name + ": " + info.state + (info.transport ? " (" + info.transport + ")" : "");
        dot.setAttribute("role", "img");
        dot.setAttribute("aria-label", dot.title);
        el.appendChild(dot);
      }
    } catch (err) {
      el.textContent = "health unavailable";
    }
  }

  // ---- light / dark theme (D-109): <html data-theme> drives the CSS tokens, AG Grid (data-ag-theme-mode) and
  // AG Charts (charts.js listens for "sg-theme"). The choice is a per-browser convenience in localStorage.
  const theme = () => (document.documentElement.dataset.theme === "light" ? "light" : "dark");
  function paintToggle() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    const t = theme();
    btn.querySelector(".theme-label").textContent = t === "light" ? "Light" : "Dark";
    btn.setAttribute("aria-label", t === "light" ? "Switch to dark theme" : "Switch to light theme");
  }
  function setTheme(t) {
    const root = document.documentElement;
    root.dataset.theme = t;
    root.dataset.agThemeMode = t;
    try { localStorage.setItem("sg-theme", t); } catch (e) { /* storage off: still switches for this page */ }
    paintToggle();
    document.dispatchEvent(new CustomEvent("sg-theme", {detail: t}));
  }
  const toggleBtn = document.getElementById("theme-toggle");
  if (toggleBtn) toggleBtn.addEventListener("click", () => setTheme(theme() === "light" ? "dark" : "light"));
  paintToggle();

  window.SG = {user, esc, api, toast, onRefresh, refresh, showCard, resultLines, confirmInDialog, proposeCancel, openDrafts,
               theme, setTheme};
  loadHealth();
})();

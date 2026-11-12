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
  // U12: "Cancel Penwright trial? You won't be charged $24.99 on Nov 22." No repeated year figure, no scare line.
  function cardHtml(card) {
    const one = card.items.length === 1 ? card.items[0] : null;
    const what = (i) => (i.trial ? "trial" : "subscription");
    const charge = (i) => i.next_charge_text
      ? `You won't be charged <strong class="money" data-testid="confirm-total">${esc(i.next_charge_text.split(" on ")[0])}</strong> on ${esc(i.next_charge_text.split(" on ").slice(1).join(" on "))}.`
      : "SubGuard cancels it in PayPal now.";
    const title = one ? `Cancel ${esc(one.short_name || one.merchant)} ${what(one)}?` : `Cancel ${card.items.length} subscriptions?`;
    const body = one ? `<p data-testid="confirm-charge">${charge(one)}</p>`
      : `<ul class="plain">${card.items.map((i) => `<li><strong>${esc(i.merchant)}</strong>: ${charge(i).replace(' data-testid="confirm-total"', "")}</li>`).join("")}</ul>`;
    return `<div class="confirm-card" data-testid="confirm-card" role="group" aria-labelledby="confirm-title">
      <h3 id="confirm-title">${title}</h3>${body}
      <div class="row"><button class="btn btn-danger" data-testid="confirm-button">Confirm cancel</button>
      <button class="btn btn-ghost" data-role="dismiss">Not now</button></div></div>`;
  }

  // Renders the card into `host`; resolves with the /api/agent/confirm result, or null if dismissed.
  // Live demo page (D-168): Priya's Cancel tap was her choice, so the card confirms itself after a short beat.
  const liveDemo = () => !!document.querySelector("[data-testid=live-demo]");
  function showCard(card, host, opts) {
    host.innerHTML = cardHtml(card);
    return new Promise((resolve) => {
      const btn = host.querySelector("[data-testid=confirm-button]");
      if (opts && opts.auto) setTimeout(() => { if (!btn.disabled && host.isConnected) btn.click(); }, 1400);
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
    const out = await showCard(card, host, {auto: liveDemo()});
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
      if (r.notice_id && window.SG.openEmail) await window.SG.openEmail(r.notice_id, {justCancelled: r.ok, auto: liveDemo()});
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
    const label = t === "light" ? "Switch to dark theme" : "Switch to light theme";  // U1: icon + tooltip, no text
    btn.setAttribute("aria-label", label);
    btn.title = label;
    btn.dataset.mode = t;
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

  // Top bar menus (D-174: Presenter, avatar): one open at a time; outside click, Escape or a link closes them.
  const menus = () => Array.from(document.querySelectorAll("details.menu[open]"));
  document.addEventListener("click", (ev) => {
    menus().forEach((m) => { if (!m.contains(ev.target) || ev.target.closest(".menu-body a")) m.open = false; });
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    menus().forEach((m) => { m.open = false; m.querySelector("summary").focus(); });
  });

  // Money saved: a short burst of coins out of `el` and a "+amount" that floats up (decoration only, aria-hidden;
  // skipped with reduced motion). `label` is the amount text from the server, never computed here (R7).
  function celebrate(el, label) {
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.querySelectorAll(".coin-burst").forEach((b) => b.remove());
    const burst = document.createElement("span");
    burst.className = "coin-burst";
    burst.setAttribute("aria-hidden", "true");
    const sym = (label && label.match(/^[^\d\s-]+/)) ? label.match(/^[^\d\s-]+/)[0] : "$";
    for (let i = 0; i < 12; i++) {
      const c = document.createElement("span");
      const a = (-160 + (140 * i) / 11) * Math.PI / 180; // a fan, up and out
      const r = 70 + Math.random() * 50;
      c.className = "coin";
      c.textContent = sym;
      c.style.cssText = `--dx:${Math.cos(a) * r}px;--dy:${Math.sin(a) * r}px;--rot:${Math.random() * 360 - 180}deg;--d:${i * 35}ms`;
      burst.appendChild(c);
    }
    if (label) {
      const plus = document.createElement("span");
      plus.className = "coin-plus";
      plus.textContent = `+${label} saved`;
      burst.appendChild(plus);
    }
    el.classList.remove("is-celebrating"); void el.offsetWidth; el.classList.add("is-celebrating");
    el.appendChild(burst);
    setTimeout(() => { burst.remove(); el.classList.remove("is-celebrating"); }, 2200);
  }

  window.SG = {user, esc, api, toast, onRefresh, refresh, showCard, resultLines, confirmInDialog, proposeCancel, openDrafts,
               theme, setTheme, celebrate};
  loadHealth();
})();

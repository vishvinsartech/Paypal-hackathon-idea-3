// "Subscribed via PayPal ✓" card (D-113). Standalone (the shop has no app.js): status, plan and billing cycles
// come from GET /api/subscriptions/{id}/paypal, which reads them LIVE from PayPal (never assumed). After a cancel
// the same card shows CANCELLED (again read from PayPal), the cancel call's ids, and "View in PayPal sandbox".
//   PayPalCard.mount(el, subId, user)   one card (shop confirmation)
//   [data-paypal-cards] sections          all of the user's cards (both dashboards); re-read from PayPal only
//                                         when our own status for a subscription changes, not on every tick.
(function () {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const css = `
  .pp-card{border:1px solid var(--line,#c8d4e3);border-left:4px solid #0070e0;border-radius:10px;padding:12px 16px;margin:10px 0;background:var(--navy-900,#f7f9fc);color:var(--text,#102036);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
  .pp-card.pp-cancelled{border-left-color:#6b7280}
  .pp-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
  .pp-mark{font:800 13px system-ui,sans-serif;color:#fff;background:#003087;border-radius:6px;padding:2px 8px;letter-spacing:.02em}
  .pp-title{font-weight:700;font-size:15px}
  .pp-status{font-weight:800;font-size:12px;border-radius:999px;padding:2px 10px;color:#fff;background:#1b8f85}
  .pp-status.CANCELLED,.pp-status.EXPIRED{background:#4b5563}.pp-status.SUSPENDED,.pp-status.APPROVAL_PENDING,.pp-status.APPROVED{background:#8a5a00}
  .pp-grid{display:grid;grid-template-columns:max-content 1fr;gap:3px 14px;margin:0}
  .pp-grid dt{color:var(--muted,#52627a);font-size:12.5px}.pp-grid dd{margin:0;overflow-wrap:anywhere}
  .pp-grid code{font-size:12.5px}.pp-cycles{margin:0;padding-left:18px}
  .pp-meta{color:var(--muted,#52627a);font-size:12px;margin:6px 0 0}
  .pp-link{display:inline-block;margin-top:8px;font-weight:600}
  .pp-warn{color:#b77900;font-size:12.5px;margin:4px 0 0}`;
  if (!document.getElementById("pp-card-css")) {
    const s = document.createElement("style");
    s.id = "pp-card-css";
    s.textContent = css;
    document.head.appendChild(s);
  }

  async function load(subId, user) {
    const res = await fetch(`/api/subscriptions/${encodeURIComponent(subId)}/paypal?user=${encodeURIComponent(user)}`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.reason || data.error || `HTTP ${res.status}`);
    return data;
  }

  function html(c) {
    if (!c.ok) {
      return `<section class="pp-card" data-testid="paypal-subscribed"><div class="pp-head"><span class="pp-mark">PayPal</span>
        <span class="pp-title">PayPal subscription</span></div><p class="pp-warn">${esc(c.error)}</p>
        <p class="pp-meta">Subscription <code data-testid="paypal-sub-id">${esc(c.paypal_id)}</code></p></section>`;
    }
    const cancelled = c.status === "CANCELLED";
    const title = cancelled ? "Cancelled in PayPal ✓" : (c.status === "ACTIVE" ? "Subscribed via PayPal ✓" : "PayPal subscription");
    const when = (c.checked_at || "").replace("T", " ").slice(0, 19);
    const created = c.created ? `<dt>Created</dt><dd>by SubGuard's server, PayPal-Request-Id <code>${esc(c.created.request_id)}</code></dd>` : "";
    // Over MCP the cancel is a tool call: our id is SubGuard's reference, not a PayPal-Request-Id header.
    const idLabel = c.cancel && c.cancel.transport === "mcp" ? "via the PayPal MCP tool, SubGuard ref" : "PayPal-Request-Id";
    const cancel = c.cancel ? `<dt>Cancel call</dt><dd>${idLabel} <code>${esc(c.cancel.request_id)}</code>${c.cancel.debug_id ? ` · debug id <code>${esc(c.cancel.debug_id)}</code>` : ""}${c.cancel.transport === "mcp" ? "" : ` · via ${esc(c.cancel.transport)}`}</dd>` : "";
    const link = c.autopay_url ? `<a class="pp-link" href="${esc(c.autopay_url)}" target="_blank" rel="noopener" data-testid="paypal-autopay-link">View in PayPal sandbox ↗</a>` : "";
    return `<section class="pp-card${cancelled ? " pp-cancelled" : ""}" data-testid="paypal-subscribed" data-status="${esc(c.status)}">
      <div class="pp-head"><span class="pp-mark">PayPal</span><span class="pp-title">${title}</span>
        <span class="pp-status ${esc(c.status)}" data-testid="paypal-status">${esc(c.status)}</span></div>
      <dl class="pp-grid">
        <dt>Subscription ID</dt><dd><code data-testid="paypal-sub-id">${esc(c.paypal_id)}</code></dd>
        <dt>Plan</dt><dd>${esc(c.plan_name)} <span class="pp-meta">(<code>${esc(c.plan_id)}</code>)</span></dd>
        <dt>Billing cycles</dt><dd><ol class="pp-cycles" data-testid="paypal-cycles">${c.cycles.map((x) => `<li>${esc(x.text)}</li>`).join("")}</ol></dd>
        ${created}${cancel}
      </dl>
      <p class="pp-meta">Status, plan and cycles fetched live from PayPal at ${esc(when)} UTC via ${esc(c.transport)}${c.debug_id ? ` · debug id <code>${esc(c.debug_id)}</code>` : ""} · ${esc(c.source)}</p>
      ${c.matches_local ? "" : `<p class="pp-warn">PayPal says ${esc(c.status)}; SubGuard's copy says ${esc(c.local_status)}. PayPal is the source of truth.</p>`}
      ${link}</section>`;
  }

  async function mount(el, subId, user) {
    el.innerHTML = `<p class="pp-meta">Checking the subscription with PayPal…</p>`;
    try {
      el.innerHTML = html(await load(subId, user));
    } catch (err) {
      el.innerHTML = `<p class="pp-warn">${esc(err.message)}</p>`;
    }
  }

  // ---- dashboards: one card per subscription, re-read from PayPal when our status for it changes ------------
  const hosts = Array.from(document.querySelectorAll("[data-paypal-cards]"));
  const user = (document.body && document.body.dataset.user) || "priya";
  const seen = new Map(); // subscription id -> our status when its card was last read from PayPal
  async function sync() {
    if (!hosts.length || document.hidden) return;
    let subs;
    try {
      subs = (await (await fetch(`/api/subscriptions?user=${encodeURIComponent(user)}`)).json())
        .filter((s) => s.status !== "APPROVAL_PENDING");
    } catch (e) { return; }
    for (const host of hosts) {
      const box = host.querySelector("[data-paypal-list]") || host;
      host.hidden = !subs.length;
      if (!subs.length) { box.innerHTML = ""; seen.clear(); continue; }
      for (const s of subs) {
        let slot = box.querySelector(`[data-sub="${CSS.escape(s.id)}"]`);
        if (!slot) {
          slot = document.createElement("div");
          slot.dataset.sub = s.id;
          box.appendChild(slot);
        }
        const key = `${host.id}:${s.id}`;
        if (seen.get(key) !== s.status) {
          seen.set(key, s.status);
          mount(slot, s.id, user);
        }
      }
    }
  }
  sync();
  setInterval(sync, 4000);
  window.PayPalCard = {mount, sync};
})();

// "Subscribed via PayPal ✓" card (D-113). Standalone (the shop has no app.js): status, plan and billing cycles
// come from GET /api/subscriptions/{id}/paypal, which reads them LIVE from PayPal (never assumed). After a cancel
// the same card shows CANCELLED (again read from PayPal), the cancel call's ids, and "View in PayPal sandbox".
//   PayPalCard.mount(el, subId, user)   one full card (shop confirmation)
//   [data-paypal-cards] sections          both dashboards (D-121): the latest run as a compact strip (ids and debug
//                                         ids under "details"), earlier runs folded into one-line rows. Each is
//                                         re-read from PayPal only when our own status for it changes.
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
  .pp-warn{color:#b77900;font-size:12.5px;margin:4px 0 0}
  .pp-strip{padding:8px 14px;margin:0}.pp-strip .pp-head{margin:0}.pp-strip .pp-link{margin:0 0 0 auto}
  .pp-plan{font-weight:700}.pp-line{margin:2px 0 0;font-size:13.5px}
  .pp-more{margin-top:4px}.pp-more>summary{cursor:pointer;color:var(--muted,#52627a);font-size:12px}
  .pp-more .pp-grid{margin-top:6px}
  .pp-earlier{margin-top:8px;font-size:13px}.pp-earlier>summary{cursor:pointer;color:var(--muted,#52627a)}
  .pp-earlier ul{list-style:none;margin:6px 0 0;padding:0}
  .pp-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:4px 0;border-top:1px solid var(--line,#c8d4e3)}
  .pp-row .pp-mark{font-size:11px;padding:1px 6px}.pp-row .pp-status{font-size:11px}.pp-row .pp-link,.pp-row .pp-meta{margin:0}`;
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

  // PayPal's own timestamps, in the viewer's time zone (D-115).
  const local = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? esc(iso) : `<time datetime="${esc(iso)}" title="${esc(d.toISOString())}">${esc(d.toLocaleString(undefined,
      {weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short"}))}</time>`;
  };

  const titleOf = (c) => c.status === "CANCELLED" ? "Cancelled in PayPal ✓" : (c.status === "ACTIVE" ? "Subscribed via PayPal ✓" : "PayPal subscription");
  const pill = (c, testid = true) => `<span class="pp-status ${esc(c.status)}"${testid ? ' data-testid="paypal-status"' : ""}>${esc(c.status)}</span>`;
  const linkOf = (c) => c.autopay_url ? `<a class="pp-link" href="${esc(c.autopay_url)}" target="_blank" rel="noopener" data-testid="paypal-autopay-link">View in PayPal sandbox ↗</a>` : "";
  const mismatch = (c) => c.matches_local ? "" : `<p class="pp-warn">PayPal says ${esc(c.status)}; SubGuard's copy says ${esc(c.local_status)}. PayPal is the source of truth.</p>`;
  const fetched = (c) => c.transport === "mock" ? `read from PayPal (demo data) at ${esc((c.checked_at || "").replace("T", " ").slice(0, 19))} UTC`
    : `fetched live from PayPal at ${esc((c.checked_at || "").replace("T", " ").slice(0, 19))} UTC via ${esc(c.transport)}`;

  // Started, how it was created and the cancel call's ids: the "proof" rows.
  function proofRows(c) {
    const started = c.start_time ? `<dt>Started</dt><dd data-testid="paypal-start-time">${local(c.start_time)} <span class="pp-meta">(PayPal's clock)</span></dd>` : "";
    const created = c.created ? `<dt>Created</dt><dd>by SubGuard's server, PayPal-Request-Id <code>${esc(c.created.request_id)}</code></dd>` : "";
    // Over MCP the cancel is a tool call: our id is SubGuard's reference, not a PayPal-Request-Id header.
    const idLabel = c.cancel && c.cancel.transport === "mcp" ? "via the PayPal MCP tool, SubGuard ref" : "PayPal-Request-Id";
    const cancel = c.cancel ? `<dt>Cancel call</dt><dd>${idLabel} <code>${esc(c.cancel.request_id)}</code>${c.cancel.debug_id ? ` · debug id <code>${esc(c.cancel.debug_id)}</code>` : ""}${c.cancel.transport === "mcp" || c.cancel.transport === "mock" ? "" : ` · via ${esc(c.cancel.transport)}`}</dd>` : "";
    return started + created + cancel;
  }

  function errorHtml(c, mode) {
    if (mode === "line") return `<div class="pp-row"><span class="pp-mark">PayPal</span><code>${esc(c.paypal_id)}</code><span class="pp-warn">${esc(c.error)}</span></div>`;
    return `<section class="pp-card" data-testid="paypal-subscribed"><div class="pp-head"><span class="pp-mark">PayPal</span>
        <span class="pp-title">PayPal subscription</span></div><p class="pp-warn">${esc(c.error)}</p>
        <p class="pp-meta">Subscription <code data-testid="paypal-sub-id">${esc(c.paypal_id)}</code></p></section>`;
  }

  // mode: "full" (evidence page PayPal tab: every id), "lite" (the card footer on `/`: no request or debug ids,
  // U4), "strip" / "line" (older dashboard layouts).
  function html(c, mode = "full") {
    if (!c.ok) return errorHtml(c, mode === "lite" ? "full" : mode);
    const cancelled = c.status === "CANCELLED";
    if (mode === "lite") {
      const started = c.start_time ? `<dt>Started</dt><dd data-testid="paypal-start-time">${local(c.start_time)}</dd>` : "";
      return `<div class="pp-card pp-lite${cancelled ? " pp-cancelled" : ""}" data-testid="paypal-subscribed" data-status="${esc(c.status)}">
        <div class="pp-head"><span class="pp-mark">PayPal</span><span class="pp-title">${titleOf(c)}</span>${pill(c)}${linkOf(c)}</div>
        <dl class="pp-grid"><dt>Plan</dt><dd>${esc(c.plan_name)}</dd>
          <dt>Billing</dt><dd data-testid="paypal-cycles">${c.cycles.map((x) => esc(x.text)).join(" → ")}</dd>${started}</dl>
        <p class="pp-meta">Status, plan and billing ${c.transport === "mock" ? "read from PayPal (demo data)" : "read live from PayPal"} at ${esc((c.checked_at || "").replace("T", " ").slice(11, 16))} UTC · ids on the evidence page</p>
        ${mismatch(c)}</div>`;
    }
    if (mode === "line") {
      return `<div class="pp-row" data-status="${esc(c.status)}"><span class="pp-mark">PayPal</span><code>${esc(c.paypal_id)}</code>${pill(c, false)}
        <span class="pp-meta">${esc(c.plan_name)}${c.start_time ? " · started " + local(c.start_time) : ""}</span>
        ${c.autopay_url ? `<a class="pp-link" href="${esc(c.autopay_url)}" target="_blank" rel="noopener">View ↗</a>` : ""}</div>`;
    }
    if (mode === "strip") {
      return `<section class="pp-card pp-strip${cancelled ? " pp-cancelled" : ""}" data-testid="paypal-subscribed" data-status="${esc(c.status)}">
        <div class="pp-head"><span class="pp-mark">PayPal</span><span class="pp-plan">${esc(c.plan_name)}</span>
          <code data-testid="paypal-sub-id">${esc(c.paypal_id)}</code>${pill(c)}${linkOf(c)}</div>
        <p class="pp-line" data-testid="paypal-cycles">${c.cycles.map((x) => esc(x.text)).join(" → ")}</p>
        ${mismatch(c)}
        <details class="pp-more"><summary>${titleOf(c)} · status, plan and cycles ${fetched(c)} · details</summary>
          <dl class="pp-grid"><dt>Plan id</dt><dd><code>${esc(c.plan_id)}</code></dd>${proofRows(c)}
            <dt>Read</dt><dd>${esc(c.source)}${c.debug_id ? ` · debug id <code>${esc(c.debug_id)}</code>` : ""}</dd></dl>
        </details></section>`;
    }
    return `<section class="pp-card${cancelled ? " pp-cancelled" : ""}" data-testid="paypal-subscribed" data-status="${esc(c.status)}">
      <div class="pp-head"><span class="pp-mark">PayPal</span><span class="pp-title">${titleOf(c)}</span>${pill(c)}</div>
      <dl class="pp-grid">
        <dt>Subscription ID</dt><dd><code data-testid="paypal-sub-id">${esc(c.paypal_id)}</code></dd>
        <dt>Plan</dt><dd>${esc(c.plan_name)} <span class="pp-meta">(<code>${esc(c.plan_id)}</code>)</span></dd>
        <dt>Billing cycles</dt><dd><ol class="pp-cycles" data-testid="paypal-cycles">${c.cycles.map((x) => `<li>${esc(x.text)}</li>`).join("")}</ol></dd>
        ${proofRows(c)}
      </dl>
      <p class="pp-meta">Status, plan and cycles ${fetched(c)}${c.debug_id ? ` · debug id <code>${esc(c.debug_id)}</code>` : ""} · ${esc(c.source)}</p>
      ${mismatch(c)}${linkOf(c)}</section>`;
  }

  async function mount(el, subId, user, mode = "full") {
    if (!el.innerHTML) el.innerHTML = `<p class="pp-meta">Checking the subscription with PayPal…</p>`;
    try {
      el.innerHTML = html(await load(subId, user), mode);
    } catch (err) {
      el.innerHTML = `<p class="pp-warn">${esc(err.message)}</p>`;
    }
  }

  // ---- dashboards: latest run as a strip, earlier runs folded; re-read from PayPal when our status changes ----
  const hosts = Array.from(document.querySelectorAll("[data-paypal-cards]"));
  const user = (document.body && document.body.dataset.user) || "priya";
  const seen = new Map(); // host:mode:subscription id -> our status when it was last read from PayPal
  const at = (s) => (s.registered_at ? Date.parse(s.registered_at) : 0) || 0;

  function show(host, el, s, mode) {
    const key = `${host.id}:${mode}:${s.id}`;
    if (seen.get(key) !== s.status) {
      seen.set(key, s.status);
      mount(el, s.id, user, mode);
    }
  }

  function row(list, subId) {
    let li = list.querySelector(`:scope > [data-sub="${CSS.escape(subId)}"]`);
    if (!li) {
      li = document.createElement("li");
      li.dataset.sub = subId;
    }
    list.appendChild(li); // (re)appending in order keeps the list newest first
    return li;
  }

  async function sync() {
    if (!hosts.length || document.hidden) return;
    let subs;
    try {
      subs = (await (await fetch(`/api/subscriptions?user=${encodeURIComponent(user)}`)).json())
        .filter((s) => s.status !== "APPROVAL_PENDING")
        .sort((a, b) => at(b) - at(a)); // newest first
    } catch (e) { return; }
    for (const host of hosts) {
      const box = host.querySelector("[data-paypal-list]") || host;
      host.hidden = !subs.length;
      if (!subs.length) { box.innerHTML = ""; seen.clear(); continue; }
      if (!box.querySelector("[data-pp-latest]")) {
        box.innerHTML = `<div data-pp-latest></div><details class="pp-earlier" data-pp-earlier data-testid="paypal-earlier" hidden>
          <summary></summary><ul></ul></details>`;
      }
      const [latest, ...earlier] = subs;
      const top = box.querySelector("[data-pp-latest]");
      if (top.dataset.sub !== latest.id) {
        top.dataset.sub = latest.id;
        top.innerHTML = "";
        seen.delete(`${host.id}:strip:${latest.id}`);
      }
      show(host, top, latest, "strip");
      const fold = box.querySelector("[data-pp-earlier]");
      const list = fold.querySelector("ul");
      const keep = new Set(earlier.map((s) => s.id));
      list.querySelectorAll(":scope > li").forEach((li) => {
        if (!keep.has(li.dataset.sub)) { li.remove(); seen.delete(`${host.id}:line:${li.dataset.sub}`); }
      });
      for (const s of earlier) show(host, row(list, s.id), s, "line");
      fold.hidden = !earlier.length;
      fold.querySelector("summary").textContent = `${earlier.length} earlier run${earlier.length === 1 ? "" : "s"} (read live from PayPal)`;
    }
  }
  sync();
  setInterval(sync, 4000);
  window.PayPalCard = {mount, sync};
})();

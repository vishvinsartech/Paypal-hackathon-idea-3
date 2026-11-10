// All AG Grid setup (Community 36.2.0 from a pinned CDN, D-060): subscriptions, audit log, findings.
(function () {
  "use strict";
  if (!window.agGrid || !window.SG) return;
  const {user, esc, api, onRefresh} = window.SG;
  const AG = window.agGrid;
  if (AG.ModuleRegistry && AG.AllCommunityModule) AG.ModuleRegistry.registerModules([AG.AllCommunityModule]);
  const theme = AG.themeQuartz.withParams({
    backgroundColor: "#11213a", foregroundColor: "#e8eef7", headerBackgroundColor: "#1a2e4d",
    accentColor: "#2ec4b6", borderColor: "#23406b", oddRowBackgroundColor: "#0f1d33",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", fontSize: 13, browserColorScheme: "dark",
    rowHoverColor: "rgba(46,196,182,0.08)", valueChangeValueHighlightBackgroundColor: "rgba(46,196,182,0.35)",
  });
  // Motion: rows animate when they move, changed cells flash teal, new audit entries flash (off for reduced motion).
  const motion = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const base = {theme, animateRows: motion, suppressCellFocus: false, domLayout: "autoHeight",
                defaultColDef: {sortable: true, filter: true, resizable: true, flex: 1, minWidth: 90}};
  const html = (s) => { const d = document.createElement("span"); d.innerHTML = s; return d; };

  // ---- cell renderers -----------------------------------------------------------------------
  function statusPill(p) {
    const r = p.data;
    const id = `status-${r.merchant_id}`;
    return html(`<span class="pill pill-${esc(String(p.value).toLowerCase())}" data-testid="${esc(id)}">${esc(p.value)}</span>`);
  }
  function riskBar(p) {
    if (p.value == null) return html(`<span class="muted">—</span>`);
    const lvl = p.value >= 60 ? "high" : p.value >= 30 ? "mid" : "low";
    return html(`<span class="risk-cell risk-${lvl}" data-testid="risk-score" aria-label="Risk ${p.value} out of 100"><span class="risk"><span class="risk-fill" style="width:${p.value}%"></span></span><span class="risk-num">${p.value}</span></span>`);
  }
  function actions(p) {
    const r = p.data;
    const parts = [`<a class="btn btn-ghost btn-sm" href="/subscriptions/${encodeURIComponent(r.id)}?user=${user}" data-testid="view-review-${esc(r.merchant_id)}">View</a>`];
    if (r.status === "ACTIVE") {
      parts.push(`<button class="btn btn-ghost btn-sm" data-keep="${esc(r.id)}">Keep</button>`);
      parts.push(`<button class="btn btn-danger btn-sm" data-cancel="${esc(r.id)}" data-testid="grid-cancel-${esc(r.merchant_id)}">Cancel</button>`);
    }
    return html(parts.join(" "));
  }

  // ---- subscriptions grid -------------------------------------------------------------------
  const subsEl = document.getElementById("subs-grid");
  if (subsEl) {
    const grid = AG.createGrid(subsEl, Object.assign({}, base, {
      rowData: [], getRowId: (p) => p.data.id,
      defaultColDef: Object.assign({}, base.defaultColDef, {enableCellChangeFlash: motion}),
      columnDefs: [
        {field: "merchant", headerName: "Merchant"},
        {field: "plan", headerName: "Plan"},
        {field: "status", headerName: "PayPal status", cellRenderer: statusPill},
        {field: "next_charge_text", headerName: "Next charge"},
        {field: "risk", headerName: "Risk", cellRenderer: riskBar, minWidth: 130},
        {field: "last_used_day", headerName: "Last used", valueFormatter: (p) => p.value == null ? "never" : "Day " + p.value},
        {field: "timer_text", headerName: "Timer", valueFormatter: (p) => p.value || "—", minWidth: 200},
        {headerName: "Actions", cellRenderer: actions, sortable: false, filter: false, minWidth: 210},
      ],
    }));
    onRefresh(async () => grid.setGridOption("rowData", (await api(`/api/view/subscriptions?user=${user}`)).rows));
    document.getElementById("subs-filter").addEventListener("input", (e) => grid.setGridOption("quickFilterText", e.target.value));
    subsEl.addEventListener("click", async (ev) => {
      const keep = ev.target.closest("[data-keep]");
      const cancel = ev.target.closest("[data-cancel]");
      if (keep) {
        try {
          const out = await api(`/api/subscriptions/${keep.dataset.keep}/keep`, {method: "POST", body: {user_id: user}});
          window.SG.toast(out.message);
        } catch (err) { window.SG.toast(err.message, {level: "urgent"}); }
        window.SG.refresh();
      } else if (cancel) {
        window.SG.proposeCancel([cancel.dataset.cancel], "Cancelled from the dashboard");
      }
    });
  }

  // ---- audit log grid -----------------------------------------------------------------------
  const auditEl = document.getElementById("audit-grid");
  if (auditEl) {
    const grid = AG.createGrid(auditEl, Object.assign({}, base, {
      rowData: [], getRowId: (p) => String(p.data.seq), domLayout: "normal", pagination: true, paginationPageSize: 50, paginationPageSizeSelector: false,
      columnDefs: [
        {field: "seq", headerName: "#", maxWidth: 80, sort: "desc"},
        {field: "ts", headerName: "Time (UTC)", valueFormatter: (p) => (p.value || "").replace("T", " ").slice(0, 19), minWidth: 160},
        {field: "sim_day", headerName: "Day", maxWidth: 80},
        {field: "actor", headerName: "Actor", maxWidth: 120},
        {field: "user_id", headerName: "User", maxWidth: 100},
        {field: "event", headerName: "Event", minWidth: 170},
        {field: "rule_id", headerName: "Rule", maxWidth: 90},
        {field: "decision", headerName: "Decision", maxWidth: 110},
        {field: "transport", headerName: "Transport", maxWidth: 110},
        {field: "paypal_debug_id", headerName: "PayPal debug id"},
        {field: "result", headerName: "Result"},
        {field: "reason", headerName: "Reason", minWidth: 220, tooltipField: "reason"},
      ],
    }));
    let maxSeq = null; // flash entries that arrive after the first load
    onRefresh(async () => {
      const rows = await api("/api/audit-log");
      grid.setGridOption("rowData", rows);
      const top = rows.reduce((m, r) => Math.max(m, r.seq), 0);
      if (motion && maxSeq !== null && top > maxSeq) {
        const fresh = [];
        grid.forEachNode((n) => { if (n.data.seq > maxSeq) fresh.push(n); });
        grid.flashCells({rowNodes: fresh, flashDuration: 900, fadeDuration: 900});
      }
      maxSeq = top; // after a reset the log shrinks, and this follows it down
      const v = await api("/api/audit-log/verify");
      const chain = document.getElementById("chain");
      chain.textContent = v.ok ? `chain verified ✓ (${v.entries} entries)` : `chain BROKEN ✗ ${v.reason || ""}`;
      chain.className = "chain " + (v.ok ? "ok" : "bad");
    });
    document.getElementById("audit-filter").addEventListener("input", (e) => grid.setGridOption("quickFilterText", e.target.value));
    document.getElementById("audit-export").addEventListener("click", () => grid.exportDataAsCsv({fileName: "subguard-audit-log.csv"}));
  }

  // ---- findings grid (subscription page) ----------------------------------------------------------
  const findEl = document.getElementById("findings-grid");
  if (findEl) {
    const rows = JSON.parse(document.getElementById("findings-data").textContent);
    AG.createGrid(findEl, Object.assign({}, base, {
      rowData: rows,
      columnDefs: [
        {field: "type", headerName: "Type", minWidth: 200, cellRenderer: (p) => html(`<span class="chip" data-testid="finding-${esc(p.value)}">${esc(p.value)}</span>`)},
        {field: "severity", headerName: "Severity", maxWidth: 100, sort: "desc"},
        {field: "plain_english", headerName: "In plain English", minWidth: 260, wrapText: true, autoHeight: true},
        {field: "quote", headerName: "Verbatim quote", minWidth: 260, wrapText: true, autoHeight: true},
        {field: "money_impact_usd_year", headerName: "Money / yr", maxWidth: 120, valueFormatter: (p) => p.value ? "$" + p.value : "—"},
        {field: "source", headerName: "Source", maxWidth: 120},
      ],
    }));
  }
  const subAuditEl = document.getElementById("sub-audit-grid");
  if (subAuditEl) {
    const grid = AG.createGrid(subAuditEl, Object.assign({}, base, {
      rowData: [], columnDefs: [
        {field: "seq", headerName: "#", maxWidth: 80}, {field: "sim_day", headerName: "Day", maxWidth: 80},
        {field: "actor", maxWidth: 120}, {field: "event", minWidth: 170}, {field: "rule_id", headerName: "Rule", maxWidth: 90},
        {field: "decision", maxWidth: 110}, {field: "transport", maxWidth: 110}, {field: "result"}, {field: "reason", minWidth: 220},
      ],
    }));
    api(`/api/audit-log?subscription_id=${encodeURIComponent(subAuditEl.dataset.sub)}`).then((rows) => grid.setGridOption("rowData", rows));
  }
})();

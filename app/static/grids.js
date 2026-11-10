// All AG Grid setup (Community 36.2.0 from a pinned CDN, D-060): audit log (Live demo), userA's activity list,
// findings + per-subscription audit (subscription page). Subscriptions are cards on userA's dashboard (D-112).
(function () {
  "use strict";
  if (!window.agGrid || !window.SG) return;
  const {user, esc, api, onRefresh} = window.SG;
  const AG = window.agGrid;
  if (AG.ModuleRegistry && AG.AllCommunityModule) AG.ModuleRegistry.registerModules([AG.AllCommunityModule]);
  // One theme, two modes (D-109): <html data-ag-theme-mode="light|dark"> picks the params (set by the theme toggle).
  const theme = AG.themeQuartz
    .withParams({fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", fontSize: 13})
    .withParams({
      backgroundColor: "#ffffff", foregroundColor: "#102036", headerBackgroundColor: "#e7edf5",
      accentColor: "#0b7f76", borderColor: "#c8d4e3", oddRowBackgroundColor: "#f6f9fc", browserColorScheme: "light",
      rowHoverColor: "rgba(11,127,118,0.07)", valueChangeValueHighlightBackgroundColor: "rgba(11,127,118,0.25)",
    }, "light")
    .withParams({
      backgroundColor: "#11213a", foregroundColor: "#e8eef7", headerBackgroundColor: "#1a2e4d",
      accentColor: "#2ec4b6", borderColor: "#23406b", oddRowBackgroundColor: "#0f1d33", browserColorScheme: "dark",
      rowHoverColor: "rgba(46,196,182,0.08)", valueChangeValueHighlightBackgroundColor: "rgba(46,196,182,0.35)",
    }, "dark");
  // Motion: rows animate when they move, changed cells flash teal, new audit entries flash (off for reduced motion).
  const motion = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const base = {theme, animateRows: motion, suppressCellFocus: false, domLayout: "autoHeight",
                defaultColDef: {sortable: true, filter: true, resizable: true, flex: 1, minWidth: 90}};
  const html = (s) => { const d = document.createElement("span"); d.innerHTML = s; return d; };

  // ---- userA's activity list (/user): her timeline from the audit log, filterable by who acted ---------------
  const actEl = document.getElementById("activity-grid");
  if (actEl) {
    let who = "all";
    const whoCell = (p) => html(`<span class="who who-${esc(p.data.kind)}">${esc(p.value)}</span>`);
    const grid = AG.createGrid(actEl, Object.assign({}, base, {
      rowData: [], getRowId: (p) => String(p.data.seq), animateRows: false,  // wrapped rows: no slide on filter
      defaultColDef: {sortable: true, resizable: true, filter: false},
      isExternalFilterPresent: () => who !== "all",
      doesExternalFilterPass: (n) => (n.data.who === "Safety timer" ? "SubGuard" : n.data.who) === who,
      overlayNoRowsTemplate: "Nothing yet. Your story starts when you click PayPal on a trial.",
      columnDefs: [
        {field: "day", headerName: "Day", width: 100, valueFormatter: (p) => "Day " + p.value},  // API order = log order
        {field: "who", headerName: "Who", width: 140, cellRenderer: whoCell},
        {field: "text", headerName: "What happened", flex: 1, minWidth: 260, wrapText: true, autoHeight: true},
        {field: "rule_id", headerName: "Rule", width: 90, valueFormatter: (p) => p.value || ""},
      ],
    }));
    onRefresh(async () => grid.setGridOption("rowData", await api(`/api/activity?user=${user}`)));
    document.querySelectorAll(".feed-filter button").forEach((b) => b.addEventListener("click", () => {
      who = b.dataset.who;
      document.querySelectorAll(".feed-filter button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      grid.onFilterChanged();
    }));
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

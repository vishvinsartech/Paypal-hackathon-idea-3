// All AG Grid setup (Community 36.2.0 from a pinned CDN, D-060): audit log (Live demo), userA's subscription history,
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

  // ---- userA's subscription history (/user, D-118): one row per subscription, search + status filter + CSV ----
  const histEl = document.getElementById("history-grid");
  if (histEl) {
    const search = document.getElementById("hist-search");
    const status = document.getElementById("hist-status");
    // "Day N" plus the calendar date in the viewer's time zone (dates come from code, D-115).
    const dayDate = (dayKey, atKey) => (p) => {
      const day = p.data[dayKey];
      if (day === null || day === undefined) return "—";
      const at = p.data[atKey] ? new Date(p.data[atKey]) : null;
      const date = at && !isNaN(at) ? at.toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric"}) : "";
      return `Day ${day}${date ? " · " + date : ""}`;
    };
    const grid = AG.createGrid(histEl, Object.assign({}, base, {
      rowData: [], getRowId: (p) => p.data.id, tooltipShowDelay: 200,
      isExternalFilterPresent: () => status.value !== "",
      doesExternalFilterPass: (n) => n.data.status === status.value,
      overlayNoRowsTemplate: "No subscriptions yet. Your history starts when you approve a trial in PayPal.",
      columnDefs: [
        {field: "merchant", headerName: "Subscription", minWidth: 190, pinned: "left",
         cellRenderer: (p) => html(`<a href="/subscriptions/${encodeURIComponent(p.data.id)}?user=${encodeURIComponent(user)}">${esc(p.value)}</a> <span class="muted small">${esc(p.data.plan)}</span>`),
         getQuickFilterText: (p) => `${p.value} ${p.data.plan}`},
        {field: "status", headerName: "Status", minWidth: 120,
         cellRenderer: (p) => html(`<span class="pill pill-${esc(String(p.value).toLowerCase())}">${p.value === "ACTIVE" ? "Active" : esc(p.value === "CANCELLED" ? "Cancelled" : p.value)}</span>`)},
        {field: "price", headerName: "Price", minWidth: 110},
        {field: "signup_day", headerName: "Subscribed", minWidth: 160, valueFormatter: dayDate("signup_day", "subscribed_at")},
        {field: "trial_end_day", headerName: "Free trial ends", minWidth: 160, valueFormatter: dayDate("trial_end_day", "trial_end_at")},
        {field: "deadline_day", headerName: "Real last day to cancel", minWidth: 180, valueFormatter: dayDate("deadline_day", "deadline_at")},
        {field: "next_charge", headerName: "Next charge", minWidth: 200, tooltipField: "next_charge"},
        {field: "outcome", headerName: "Outcome", minWidth: 230, tooltipField: "outcome"},
        {field: "timer", headerName: "Safety timer", minWidth: 170, tooltipField: "timer"},
        {field: "risk", headerName: "Risk", minWidth: 90, filter: "agNumberColumnFilter",
         valueFormatter: (p) => (p.value === null || p.value === undefined ? "—" : `${p.value}/100`)},
        {field: "last_event", headerName: "Latest event", minWidth: 260,
         tooltipValueGetter: (p) => (p.data.event_log || []).join("\n") || null,
         getQuickFilterText: (p) => (p.data.event_log || []).join(" ")},
        {field: "events", headerName: "Events", minWidth: 90, filter: "agNumberColumnFilter"},
      ],
    }));
    onRefresh(async () => grid.setGridOption("rowData", await api(`/api/subscription-history?user=${user}`)));
    search.addEventListener("input", () => grid.setGridOption("quickFilterText", search.value));
    status.addEventListener("change", () => grid.onFilterChanged());
    document.getElementById("hist-clear").addEventListener("click", () => {
      search.value = ""; status.value = "";
      grid.setGridOption("quickFilterText", "");
      grid.setFilterModel(null);
      grid.applyColumnState({defaultState: {sort: null}});
      grid.onFilterChanged();
    });
    document.getElementById("hist-export").addEventListener("click", () => grid.exportDataAsCsv({
      fileName: "subguard-subscription-history.csv",
      columnKeys: ["merchant", "status", "price", "signup_day", "trial_end_day", "deadline_day", "next_charge",
                   "outcome", "timer", "risk", "last_event", "events"],  // value formatters apply (AG Grid 31+)
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

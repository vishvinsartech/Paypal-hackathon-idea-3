// Priya's charts with AG Charts Community 14.2.0 (pinned CDN, MIT; D-108), on her dashboard only. Every element with
// data-chart="cost|risk|usage" gets a chart fed by GET /api/analytics. Numbers come from code (money
// is computed server-side from the PayPal plan; this file only plots it). Charts follow the light/dark toggle.
(function () {
  "use strict";
  const lib = window.agCharts;
  if (!lib || !window.SG) return;
  const {user, api, onRefresh} = window.SG;
  const els = Array.from(document.querySelectorAll("[data-chart]"));
  if (!els.length) return;
  if (lib.ModuleRegistry && lib.AllCommunityModule) lib.ModuleRegistry.registerModules([lib.AllCommunityModule]);
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const COLORS = {
    dark: {teal: "#2ec4b6", amber: "#f5b942", blue: "#6f9cff", red: "#ff5a5f", mint: "#9ff3ea", grey: "#8fa3bf"},
    light: {teal: "#0b7f76", amber: "#b77900", blue: "#2f5fd0", red: "#c8323a", mint: "#3aa79c", grey: "#6b7a90"},
  };
  const live = new Map(); // element -> {chart, kind}
  let last = null;
  let lastJson = "";

  const mode = () => window.SG.theme();
  const C = () => COLORS[mode()];
  const num = (s) => Number(s);
  function theme() {
    const c = C();
    return {
      baseTheme: mode() === "light" ? "ag-default" : "ag-default-dark",
      palette: {fills: [c.teal, c.amber, c.blue, c.red, c.mint, c.grey], strokes: [c.teal, c.amber, c.blue, c.red, c.mint, c.grey]},
      overrides: {common: {background: {fill: "transparent"}, animation: {enabled: !reduce}}},
    };
  }

  // ---- one builder per chart kind -----------------------------------------------------------------
  const BUILD = {
    cost(a) {
      const c = C(), sym = a.cost.symbol || "";
      const money = (v) => sym + Number(v).toFixed(2);
      return {
        data: a.cost.rows.map((r) => ({month: r.month, if_kept: num(r.if_kept), you_pay: num(r.you_pay)})),
        series: [
          {type: "area", xKey: "month", yKey: "if_kept", yName: a.cost.preview ? "If she keeps it" : "If you'd kept it",
           fill: c.amber, fillOpacity: 0.18, stroke: c.amber, strokeWidth: 2,
           tooltip: {renderer: (p) => ({content: money(p.datum.if_kept)})}},
          {type: "line", xKey: "month", yKey: "you_pay", yName: "What you pay", stroke: c.teal, strokeWidth: 3,
           marker: {fill: c.teal, size: 6}, tooltip: {renderer: (p) => ({content: money(p.datum.you_pay)})}},
        ],
        axes: {x: {type: "category"}, y: {type: "number", label: {formatter: (p) => sym + p.value}}},
        legend: {position: "bottom"},
      };
    },
    risk(a) {
      const c = C();
      return {
        data: a.risk.parts,
        series: [{type: "bar", direction: "horizontal", xKey: "label", yKey: "points", yName: "Risk points",
                  itemStyler: (p) => ({fill: {"Hidden deadline": c.red, "Price jumps": c.amber, "Hard to cancel": c.blue, "Hard-to-read terms": c.grey}[p.datum.group] || c.teal}),
                  label: {enabled: true, placement: "outside-end", formatter: (p) => String(Math.round(p.value))}}],
        legend: {enabled: false},
      };
    },
    usage(a) {
      const c = C(), u = a.usage;
      const lines = [];
      if (u.deadline_day != null) lines.push({type: "line", value: `Day ${u.deadline_day}`, stroke: c.red, lineDash: [6, 4], label: {text: "Real deadline", color: c.red}});
      if (u.first_charge_day != null) lines.push({type: "line", value: `Day ${u.first_charge_day}`, stroke: c.amber, lineDash: [6, 4], label: {text: "First charge", color: c.amber}});
      return {
        data: u.rows,
        series: [{type: "bar", xKey: "day", yKey: "opens", yName: "Times opened", fill: c.teal, cornerRadius: 4}],
        axes: {x: {type: "category", crossLines: lines}, y: {type: "number", min: 0, max: Math.max(2, ...u.rows.map((r) => r.opens)) + 1, interval: {step: 1}}},
        legend: {enabled: false},
      };
    },
  };
  const EMPTY = {
    risk: (a) => !a.risk && "No fine-print review yet. Open the shop and click PayPal.",
    usage: (a) => !a.usage.rows.length && "No trial yet.",
    cost: (a) => !a.cost.rows.length && "No plan to chart.",
  };

  function render(el, a) {
    const kind = el.dataset.chart;
    const empty = EMPTY[kind] && EMPTY[kind](a);
    const sub = el.parentElement.querySelector("[data-chart-sub]");
    if (sub) sub.textContent = subtitle(kind, a);
    let entry = live.get(el);
    if (empty) {
      if (entry) { entry.chart.destroy(); live.delete(el); }
      el.innerHTML = `<div class="chart-empty">${window.SG.esc(empty)}</div>`;
      return;
    }
    const opts = Object.assign({container: el, theme: theme()}, BUILD[kind](a));
    if (entry) entry.chart.update(opts);
    else {
      el.innerHTML = "";
      live.set(el, {chart: lib.AgCharts.create(opts), kind});
    }
  }

  function subtitle(kind, a) {
    if (kind === "cost") return a.cost.preview
      ? `First paid year if kept: ${a.cost.if_kept_text} (from the PayPal plan)`
      : `If kept: ${a.cost.if_kept_text} · you pay: ${a.cost.you_pay_text} · protected: ${a.cost.protected_text}`;
    if (kind === "risk") return a.risk ? `${a.risk.merchant}: risk ${a.risk.score}/100, by what caused it` : "";
    if (kind === "usage") return `Opened ${a.usage.total} time${a.usage.total === 1 ? "" : "s"} during the trial`;
    return "";
  }

  async function load(force) {
    const scope = els[0].closest("[data-analytics-sub]");  // the evidence page scopes the charts to one subscription
    const a = await api(`/api/analytics?user=${user}` + (scope ? `&subscription_id=${encodeURIComponent(scope.dataset.analyticsSub)}` : ""));
    const json = JSON.stringify(a);
    if (!force && json === lastJson) return; // nothing changed: don't re-animate
    last = a;
    lastJson = json;
    els.forEach((el) => render(el, a));
  }

  document.addEventListener("sg-theme", () => { if (last) els.forEach((el) => render(el, last)); });
  onRefresh(() => load(false));
  load(true).catch((e) => console.warn("analytics", e.message));
  window.SG.charts = {reload: () => load(true)};
})();

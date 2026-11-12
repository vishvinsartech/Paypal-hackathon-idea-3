// Priya's Analytics section (D-174), AG Charts Community 14.2.0 (vendored, MIT; D-108). Three charts from
// GET /api/dashboard/analytics: upcoming charges (next 30 days), monthly spend (last 6 months), and what SubGuard
// saved (trials stopped vs price rises avoided). Every amount is computed server-side; this file only plots it.
// Charts are built the first time the section opens (they need a visible box) and follow the light/dark toggle.
(function () {
  "use strict";
  const lib = window.agCharts;
  if (!lib || !window.SG) return;
  const {user, api, onRefresh, esc} = window.SG;
  const els = Array.from(document.querySelectorAll("[data-dchart]"));
  const panel = document.querySelector("[data-panel=analytics]");
  if (!els.length || !panel) return;
  if (lib.ModuleRegistry && lib.AllCommunityModule) lib.ModuleRegistry.registerModules([lib.AllCommunityModule]);
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const COLORS = {
    dark: ["#2ec4b6", "#f5b942", "#6f9cff", "#ff8a8e", "#9ff3ea", "#8fa3bf"],
    light: ["#0b7f76", "#b77900", "#2f5fd0", "#c8323a", "#3aa79c", "#6b7a90"],
  };
  const live = new Map();
  let data = null;
  let json = "";

  const mode = () => window.SG.theme();
  const pal = () => COLORS[mode()];
  function theme() {
    return {baseTheme: mode() === "light" ? "ag-default" : "ag-default-dark",
            palette: {fills: pal(), strokes: pal()},
            overrides: {common: {background: {fill: "transparent"}, animation: {enabled: !reduce}}}};
  }
  const colour = (name) => pal()[Math.max(0, (data.merchants || []).indexOf(name)) % pal().length];
  const money = (v) => (data.symbol || "") + Number(v).toFixed(2);
  const stacked = (rows, keyX, names) => ({
    data: rows.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, k === keyX ? v : Number(v)]))),
    series: names.map((n) => ({type: "bar", xKey: keyX, yKey: n, yName: n, stacked: true, cornerRadius: 3, fill: colour(n),
                               tooltip: {renderer: (p) => ({heading: p.datum[keyX], content: `${n}: ${money(p.datum[n])}`})}})),
    axes: {x: {type: "category"}, y: {type: "number", label: {formatter: (p) => (data.symbol || "") + p.value}}},
    legend: {position: "bottom"},
  });

  const BUILD = {
    upcoming: (a) => stacked(a.upcoming.rows, "date", a.upcoming.series),
    monthly: (a) => stacked(a.monthly.rows, "month", a.monthly.series),
    saved(a) {
      const c = pal();
      return {
        data: a.saved.rows.map((r) => ({kind: r.kind, amount: Number(r.amount)})),
        series: [{type: "bar", xKey: "kind", yKey: "amount", yName: "Saved", cornerRadius: 4,
                  itemStyler: (p) => ({fill: p.datum.kind === "Trials stopped" ? c[0] : c[1]}),
                  label: {enabled: true, placement: "outside-end", formatter: (p) => money(p.value)},
                  tooltip: {renderer: (p) => ({content: money(p.datum.amount)})}}],
        axes: {x: {type: "category"}, y: {type: "number", label: {formatter: (p) => (data.symbol || "") + p.value}}},
        legend: {enabled: false},
      };
    },
  };
  const EMPTY = {
    upcoming: (a) => !a.upcoming.rows.length && "No charges in the next 30 days.",
    monthly: (a) => !a.monthly.series.length && "No charges in the last 6 months.",
    saved: () => false,
  };
  const SUB = {
    upcoming: (a) => `${a.upcoming.total} due in the next 30 days`,
    monthly: () => "What was really charged, by month",
    saved: (a) => `${a.saved.total} in total`,
  };

  function render(el) {
    const kind = el.dataset.dchart;
    const sub = document.querySelector(`[data-dchart-sub="${kind}"]`);
    if (sub) sub.textContent = SUB[kind](data);
    const empty = EMPTY[kind](data);
    const entry = live.get(el);
    if (empty) {
      if (entry) { entry.destroy(); live.delete(el); }
      el.innerHTML = `<div class="chart-empty">${esc(empty)}</div>`;
      return;
    }
    const opts = Object.assign({container: el, theme: theme()}, BUILD[kind](data));
    if (entry) entry.update(opts);
    else { el.innerHTML = ""; live.set(el, lib.AgCharts.create(opts)); }
  }
  async function load(force) {
    if (panel.hidden) return;  // built when the section opens
    const a = await api(`/api/dashboard/analytics?user=${encodeURIComponent(user)}`);
    const j = JSON.stringify(a);
    if (!force && j === json && live.size) return;
    data = a;
    json = j;
    els.forEach(render);
  }

  document.addEventListener("sg-section", (ev) => { if (ev.detail === "analytics") load(true).catch(() => {}); });
  document.addEventListener("sg-theme", () => { if (data) els.forEach(render); });
  onRefresh(() => load(false).catch(() => {}));
  load(true).catch(() => {});
})();

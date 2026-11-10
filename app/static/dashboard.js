// Dashboard panels: KPIs, alerts (+ toasts for new ones), timeline, notices, demo control bar.
(function () {
  "use strict";
  const {user, esc, api, toast, onRefresh, refresh} = window.SG;
  let seenAlerts = null; // ids already shown; null until the first load (no toasts on page load)

  // ---- KPIs + sim day -----------------------------------------------------------------------
  onRefresh(async () => {
    const k = await api(`/api/kpis?user=${user}`);
    const extra = Object.values(k.other_currencies || {}).map((t) => ` + ${t}/yr`).join("");
    document.getElementById("kpi-protected").textContent = k.money_protected_text + "/yr" + extra;
    document.getElementById("kpi-patterns").textContent = k.dark_patterns_caught;
    document.getElementById("kpi-cancelled").textContent = k.subscriptions_cancelled;
    document.getElementById("kpi-watches").textContent = k.active_watches;
  });

  // ---- alerts -------------------------------------------------------------------------------
  const ALERT_TESTID = {timer_set: "alert-timer-set", reminder: "alert-trial-check", cancelled: "alert-done",
                        blocked_charge: "blocked-charge"};
  const BTN_TESTID = {keep: "alert-keep", cancel: "alert-cancel"};

  function alertHtml(a) {
    const done = !!a.acknowledged_at;
    const buttons = done ? `<span class="muted small">Handled</span>` : a.actions.map((b) =>
      `<button class="btn btn-sm ${b.action === "cancel" ? "btn-danger" : "btn-ghost"}" data-alert="${esc(a.id)}" data-action="${esc(b.action)}" data-testid="${BTN_TESTID[b.action] || "alert-" + esc(b.action)}">${esc(b.label)}</button>`).join("");
    const delivery = Object.entries(a.delivery || {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
    return `<article class="alert alert-${esc(a.level)}${done ? " is-done" : ""}" data-testid="${ALERT_TESTID[a.kind] || "alert-" + esc(a.kind)}">
      <header><strong>${esc(a.title)}</strong><span class="muted small">Day ${a.sim_day}</span></header>
      <p>${esc(a.body)}</p><div class="row">${buttons}</div>
      <p class="muted tiny">Delivered: ${esc(delivery)}</p></article>`;
  }

  onRefresh(async () => {
    const alerts = await api(`/api/alerts?user=${user}`);
    const box = document.getElementById("alerts");
    box.innerHTML = alerts.length ? alerts.map(alertHtml).join("") : `<p class="muted">No alerts yet.</p>`;
    if (seenAlerts !== null) {
      alerts.filter((a) => !seenAlerts.has(a.id)).reverse().forEach((a) =>
        toast(a.body, {title: a.title, level: a.level, testid: "toast-alert"}));
    }
    seenAlerts = new Set(alerts.map((a) => a.id));
  });

  document.getElementById("alerts").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    btn.disabled = true;
    let popup = null;
    if (action === "restart" || action === "open_autopay") popup = window.open("about:blank", "_blank");
    try {
      const out = await api(`/api/alerts/${btn.dataset.alert}/act`, {method: "POST", body: {user_id: user, action}});
      if (out.confirm) await window.SG.confirmInDialog(out.confirm);
      else if (out.url) {
        if (popup) popup.location.href = out.url; else window.open(out.url, "_blank", "noopener");
        if (out.note) toast(out.note);
      } else if (out.message) toast(out.message);
    } catch (err) {
      if (popup) popup.close();
      toast(err.message, {level: "urgent"});
    }
    await refresh();
  });

  // ---- timeline -----------------------------------------------------------------------------
  function marker(cls, day, x, label) {
    return `<span class="tl-mark ${cls}" style="left:${x(day)}%" title="${esc(label)}" aria-label="${esc(label)}"></span>`;
  }

  onRefresh(async () => {
    const view = await api(`/api/view/subscriptions?user=${user}`);
    document.querySelectorAll(".js-day").forEach((el) => { el.textContent = view.today; });
    const box = document.getElementById("timeline");
    if (!view.rows.length) { box.innerHTML = `<p class="muted">No subscriptions yet.</p>`; return; }
    const days = view.rows.flatMap((r) => [r.signup_day, r.next_billing_day, r.timer && r.timer.fire_day]).filter((d) => d != null);
    const lo = Math.min(0, ...days), hi = Math.max(31, view.today + 3, ...days.map((d) => d + 2));
    const x = (d) => Math.max(0, Math.min(100, ((d - lo) / (hi - lo)) * 100));
    box.innerHTML = view.rows.map((r) => {
      const t = r.timer;
      const parts = [];
      if (r.trial_end_day != null) parts.push(`<span class="tl-trial" style="left:${x(r.signup_day)}%;width:${x(r.trial_end_day) - x(r.signup_day)}%" title="Trial window"></span>`);
      if (r.deadline_day != null) parts.push(marker("tl-deadline", r.deadline_day, x, `Real deadline: Day ${r.deadline_day}`));
      if (t && t.status === "PENDING") parts.push(marker("tl-timer", t.fire_day, x, `Safety timer: Day ${t.fire_day}`));
      if (r.next_billing_day != null) parts.push(marker(r.status === "ACTIVE" ? "tl-charge" : "tl-charge is-blocked", r.next_billing_day, x, `${r.status === "ACTIVE" ? "Next charge" : "Charge blocked"}: Day ${r.next_billing_day}`));
      if (r.cancelled_day != null) parts.push(marker("tl-cancel", r.cancelled_day, x, `Cancelled: Day ${r.cancelled_day}`));
      const chip = r.timer_text && t && t.status === "PENDING" ? `<span class="chip chip-teal" data-testid="timer-chip">${esc(r.timer_text)}</span>` : "";
      const step = r.step_up_text ? `<span class="muted tiny">→ ${esc(r.step_up_text)} from Day ${r.step_up_day}</span>` : "";
      return `<div class="tl-row"><div class="tl-label"><strong>${esc(r.merchant)}</strong> <span class="muted small">${esc(r.plan)}</span> ${chip} ${step}</div>
        <div class="tl-track">${parts.join("")}<span class="tl-today" style="left:${x(view.today)}%" title="Today: Day ${view.today}"></span></div></div>`;
    }).join("") + `<div class="tl-axis"><span>Day ${lo}</span><span>Day ${hi}</span></div>`;
  });

  // ---- notices ------------------------------------------------------------------------------
  onRefresh(async () => {
    const notices = await api(`/api/notices?user=${user}`);
    document.getElementById("notices").innerHTML = notices.length ? notices.map((n) => `
      <details class="notice" data-testid="cancellation-notice"><summary><strong>${esc(n.subject)}</strong> → ${esc(n.to)} · Day ${n.sim_day} · ${esc(n.delivery)}</summary>
      <pre>${esc(n.body)}</pre><p class="small">SHA-256: <code data-testid="notice-sha256">${esc(n.sha256)}</code></p></details>`).join("")
      : `<p class="muted">None yet.</p>`;
  });

  // ---- demo control bar -------------------------------------------------------------------------
  const bar = document.getElementById("demo-bar");
  async function demo(path, label) {
    try {
      await api(path, {method: "POST"});
      if (label) toast(label);
    } catch (err) {
      toast(err.message, {level: "urgent"});
    }
    await refresh();
  }
  bar.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.advance) demo(`/api/demo/advance?days=${b.dataset.advance}`);
    else if (b.dataset.jump) demo(`/api/demo/advance?to_day=${b.dataset.jump}`);
    else if (b.id === "toggle-fair-trial") demo(`/api/demo/toggle-fair-trial/${document.getElementById("fair-trial-merchant").value}`, "Fair Trial membership toggled.");
    else if (b.id === "demo-reset" && confirm("Reset the demo? This wipes the runtime data.")) {
      api("/api/demo/reset", {method: "POST"}).then(() => location.reload()).catch((e) => toast(e.message, {level: "urgent"}));
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key.toLowerCase() !== "d" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.target.closest("input, textarea, select, [contenteditable]")) return;
    bar.hidden = !bar.hidden;
  });

  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 5000);
})();

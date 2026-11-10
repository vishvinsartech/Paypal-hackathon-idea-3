// Live demo (presenter control room, D-112): Money protected, alerts (+ toasts for new ones), timeline, the
// "email ready" banner and the demo control bar. Priya's product view is /user.
// Motion: KPIs count up and glow when they change, the day chip bumps, new alerts slide in, the timeline's
// "today" line slides. CSS turns it all off under prefers-reduced-motion.
(function () {
  "use strict";
  const {user, esc, api, toast, onRefresh, refresh} = window.SG;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let seenAlerts = null; // ids already shown; null until the first load (no toasts on page load)

  // ---- KPIs + sim day -----------------------------------------------------------------------
  // Sets `text` on el; if its number changed, counts up/down to it (same prefix, suffix and decimals).
  function setKpi(id, text) {
    const el = document.getElementById(id);
    if (!el || el.textContent === String(text)) return;
    const m = String(text).match(/^([^\d-]*)(-?[\d,]*\.?\d+)(.*)$/s);
    const from = parseFloat((el.textContent.match(/-?[\d,]*\.?\d+/) || ["0"])[0].replace(/,/g, ""));
    el.closest(".kpi").classList.remove("is-bumped");
    void el.offsetWidth;
    el.closest(".kpi").classList.add("is-bumped");
    if (!m || reduce) { el.textContent = text; return; }
    const [, pre, num, post] = m;
    const to = parseFloat(num.replace(/,/g, ""));
    const decimals = (num.split(".")[1] || "").length;
    const start = performance.now();
    const fmt = (v) => pre + v.toLocaleString("en-US", {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) + post;
    (function frame(now) {
      const t = Math.min(1, (now - start) / 900);
      el.textContent = t < 1 ? fmt(from + (to - from) * (1 - Math.pow(1 - t, 3))) : text;
      if (t < 1) requestAnimationFrame(frame);
    })(start);
  }

  onRefresh(async () => {
    const k = await api(`/api/kpis?user=${user}`);
    const extra = Object.values(k.other_currencies || {}).map((t) => ` + ${t}/yr`).join("");
    setKpi("kpi-protected", k.money_protected_text + "/yr" + extra);
  });

  // ---- alerts -------------------------------------------------------------------------------
  const ALERT_TESTID = {timer_set: "alert-timer-set", reminder: "alert-trial-check", cancelled: "alert-done",
                        blocked_charge: "blocked-charge"};
  // The cancel flow is reminder Cancel -> confirmation card -> email preview, with no extra pop-ups: the preview
  // already says "Cancelled in PayPal. You won't be charged.", so that alert is listed but not toasted.
  const QUIET = new Set(["cancelled"]);
  const BTN_TESTID = {keep: "alert-keep", cancel: "alert-cancel"};

  function alertHtml(a, isNew) {
    const done = !!a.acknowledged_at;
    const buttons = done ? `<span class="muted small">Handled</span>` : a.actions.map((b) =>
      `<button class="btn btn-sm ${b.action === "cancel" ? "btn-danger" : "btn-ghost"}" data-alert="${esc(a.id)}" data-action="${esc(b.action)}" data-testid="${BTN_TESTID[b.action] || "alert-" + esc(b.action)}">${esc(b.label)}</button>`).join("");
    const delivery = Object.entries(a.delivery || {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
    return `<article class="alert alert-${esc(a.level)}${done ? " is-done" : ""}${isNew ? " is-new" : ""}" data-testid="${ALERT_TESTID[a.kind] || "alert-" + esc(a.kind)}">
      <header><strong>${esc(a.title)}</strong><span class="muted small">Day ${a.sim_day}</span></header>
      <p>${esc(a.body)}</p><div class="row">${buttons}</div>
      <p class="muted tiny">Delivered: ${esc(delivery)}</p></article>`;
  }

  onRefresh(async () => {
    const alerts = await api(`/api/alerts?user=${user}`);
    const box = document.getElementById("alerts");
    const isNew = (a) => seenAlerts !== null && !seenAlerts.has(a.id);
    box.innerHTML = alerts.length ? alerts.map((a) => alertHtml(a, isNew(a))).join("") : `<p class="muted">No alerts yet.</p>`;
    if (seenAlerts !== null) {
      alerts.filter((a) => !seenAlerts.has(a.id) && !QUIET.has(a.kind)).reverse().forEach((a) =>
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
    if (action === "open_autopay") popup = window.open("about:blank", "_blank");
    try {
      const out = await api(`/api/alerts/${btn.dataset.alert}/act`, {method: "POST", body: {user_id: user, action}});
      if (out.confirm) await window.SG.confirmInDialog(out.confirm);
      else if (out.notice_id) await window.SG.openEmail(out.notice_id);
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

  let shownRows = null; // subscription ids already on the timeline (new rows animate in)
  let lastTodayX = null;

  onRefresh(async () => {
    const view = await api(`/api/view/subscriptions?user=${user}`);
    document.querySelectorAll(".js-day").forEach((el) => {
      if (el.textContent === String(view.today)) return;
      el.textContent = view.today;
      el.classList.remove("day-bump");
      void el.offsetWidth;
      el.classList.add("day-bump");
    });
    const box = document.getElementById("timeline");
    if (!view.rows.length) {
      box.innerHTML = `<p class="muted">No subscriptions yet.</p>`;
      shownRows = new Set();
      lastTodayX = null;
      return;
    }
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
      const fresh = shownRows !== null && !shownRows.has(r.id);
      return `<div class="tl-row${fresh ? " is-new" : ""}"><div class="tl-label"><strong>${esc(r.merchant)}</strong> <span class="muted small">${esc(r.plan)}</span> ${chip} ${step}</div>
        <div class="tl-track">${parts.join("")}<span class="tl-today" style="left:${x(view.today)}%" title="Today: Day ${view.today}"></span></div></div>`;
    }).join("") + `<div class="tl-axis"><span>Day ${lo}</span><span>Day ${hi}</span></div>`;
    shownRows = new Set(view.rows.map((r) => r.id));
    // slide the "today" line from where it was to where it is now
    const todayX = x(view.today);
    const lines = box.querySelectorAll(".tl-today");
    if (lastTodayX !== null && lastTodayX !== todayX && !reduce) {
      lines.forEach((l) => { l.style.transition = "none"; l.style.left = lastTodayX + "%"; });
      void box.offsetWidth;
      lines.forEach((l) => { l.style.transition = ""; l.style.left = todayX + "%"; });
    }
    lastTodayX = todayX;
  });

  // ---- "email ready" banner (the emails themselves are on Priya's dashboard) -----------------------
  onRefresh(async () => {
    const drafts = (await api(`/api/notices?user=${user}`)).filter((n) => n.status === "draft");
    const ready = document.getElementById("email-ready");
    ready.hidden = !drafts.length;
    ready.innerHTML = drafts.map((n) => `<p><strong>Your cancellation email is ready to review and send.</strong>
      <button class="btn btn-sm" data-email-open="${esc(n.id)}" data-testid="email-review">Review email</button></p>`).join("");
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

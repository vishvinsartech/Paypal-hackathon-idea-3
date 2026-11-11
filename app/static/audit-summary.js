// Live demo "What SubGuard did" (D-121): this run only, one plain row per thing SubGuard did, from
// GET /api/audit-log/summary (built from the hash-chained audit log). "Show full log" reveals the raw AG Grid.
(function () {
  "use strict";
  if (!window.SG) return;
  const {user, esc, api, onRefresh} = window.SG;
  const body = document.getElementById("audit-sum-rows");
  if (!body) return;
  const EMPTY = "Nothing yet. When Priya starts a free trial, SubGuard's steps show here.";

  const toggle = document.getElementById("audit-toggle");
  const full = document.getElementById("audit-full");
  let count = null; // entries in the full log
  const label = () => { toggle.textContent = `${full.hidden ? "Show" : "Hide"} full log${count === null ? "" : ` (${count})`}`; };
  toggle.addEventListener("click", () => {
    full.hidden = !full.hidden;
    toggle.setAttribute("aria-expanded", String(!full.hidden));
    label();
  });

  const rule = (r) => {
    if (!r.rule_id && r.decision === "n/a") return "";
    const mark = r.decision === "blocked" ? " ✗" : (r.decision === "allowed" ? " ✓" : "");
    return `<span class="rule-chip ${esc(r.decision)}">${esc(r.rule_id || "")}${mark}</span>`;
  };

  // B4: the step tracker follows the subscription's real events, so it ticks when you click through by hand too.
  // Start demo still shows its in-progress ("active") marks; a derived state that isn't pending wins.
  const stepEls = Array.from(document.querySelectorAll("#pipeline-steps .step"));
  const fill = document.getElementById("pipe-fill");
  function applySteps(list) {
    if (!stepEls.length || !list) return;
    list.forEach((st) => {
      const el = stepEls.find((x) => x.dataset.step === st.key);
      if (!el || st.state === "pending") return;
      el.classList.remove("is-active", "is-done", "is-skipped", "is-warn");
      el.classList.add("is-" + st.state);
      if (st.detail != null) el.querySelector(".step-detail").textContent = st.detail;
      const dot = el.querySelector(".step-dot");
      if (st.state === "done" || st.state === "warn") dot.textContent = "✓";
      if (st.state === "skipped") dot.textContent = "–";
    });
    const reached = stepEls.reduce((n, x, k) => (x.matches(".is-active, .is-done, .is-warn, .is-skipped") ? k : n), 0);
    if (fill) fill.style.width = (reached / (stepEls.length - 1)) * 100 + "%";
  }

  let last = "";
  // B3: draw straight away, built from Priya's latest subscription (manual sign-up or Start demo alike).
  // Before, the table waited for the next 5 s refresh because this listener registers after the first one.
  async function render() {
    const s = await api(`/api/audit-log/summary?user=${user}`);
    applySteps(s.steps);
    const key = JSON.stringify([s.subscription_id, s.rows.map((r) => r.seq), s.full_log_entries]);
    if (key === last) return; // nothing new: leave the table (and any text selection) alone
    last = key;
    count = s.full_log_entries;
    label();
    body.innerHTML = s.rows.length ? s.rows.map((r) => `
      <tr class="sum-${esc(r.kind)}${r.decision === "blocked" ? " is-blocked" : ""}" data-testid="audit-summary-row">
        <td class="nowrap">Day ${r.day}</td>
        <td><span class="who who-${esc(r.kind)}">${esc(r.who)}</span></td>
        <td>${esc(r.text)}</td>
        <td>${rule(r)}</td>
        <td>${r.proof ? `<code title="PayPal debug id / SubGuard request id">${esc(r.proof)}</code>` : ""}</td>
      </tr>`).join("")
      : `<tr><td colspan="5" class="muted">${EMPTY}</td></tr>`;
  }
  onRefresh(render);
  render().catch((e) => console.warn("audit summary", e.message));
})();

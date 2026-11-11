// Live demo "What SubGuard did" (D-121): this run only, one plain row per thing SubGuard did, from
// GET /api/audit-log/summary (built from the hash-chained audit log). "Show full log" reveals the raw AG Grid.
(function () {
  "use strict";
  if (!window.SG) return;
  const {user, esc, api, onRefresh} = window.SG;
  const body = document.getElementById("audit-sum-rows");
  if (!body) return;

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

  let last = "";
  onRefresh(async () => {
    const s = await api(`/api/audit-log/summary?user=${user}`);
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
      : `<tr><td colspan="5" class="muted">Nothing yet. Press Start demo.</td></tr>`;
  });
})();

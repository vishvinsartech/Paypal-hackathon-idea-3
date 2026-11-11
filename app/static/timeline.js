// B7: the trial timeline, a fixed Day 0-14 view from sign-up with five labelled dots (Signed up, Check-in,
// Act by, Trial ends, First charge) and their calendar dates. All positions and dates come from the server
// (/api/view/subscriptions -> trial_dots, today_pos); this file only draws them. user.html renders the same
// markup with Jinja (_trial_dots macro), so both pages look alike.
(function () {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  function html(row) {
    const dots = (row.trial_dots || []).map((d) => `
      <li class="t5-dot is-${esc(d.state)} t5-${esc(d.side)} t5-${esc(d.key)}" style="left:${d.pos}%" data-testid="t5-${esc(d.key)}">
        <span class="t5-mark" aria-hidden="true"></span>
        <span class="t5-label"><span class="t5-name">${esc(d.label)}</span> <time>${esc(d.date)}</time></span>
      </li>`).join("");
    if (!dots) return "";
    return `<div class="t5" data-testid="trial-timeline">
      <ol class="t5-track" aria-label="Trial timeline">${dots}</ol>
      <span class="t5-today" style="left:${row.today_pos}%" title="Today" aria-hidden="true"></span>
    </div>${row.step_up_line ? `<p class="t5-step muted small" data-testid="step-up-line">Then ${esc(row.step_up_line)}</p>` : ""}`;
  }

  window.SGTimeline = {html};
})();

// Presenter bar (U6): hidden unless ?demo=1 or the D key. Day scrubber (forward only), jumps to Day 0/5/6/7/11,
// +1 day, Reset, the Fair Trial toggle for Quillnote, "Show audit log", and the 7-step indicator. The steps
// follow the subscription's real events (B4, GET /api/audit-log/summary), so a manual run ticks them too.
(function () {
  "use strict";
  if (!window.SG) return;
  const {api, toast, onRefresh, refresh} = window.SG;
  const bar = document.getElementById("demo-bar");

  // ---- audit drawer (also opened by "Show all" in What SubGuard did) ---------------------------------
  const drawer = document.getElementById("audit-drawer");
  document.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-open-audit]") && drawer) {
      drawer.showModal();
      window.dispatchEvent(new Event("resize")); // the grid measures itself once visible
    } else if (ev.target.closest("[data-close-audit]") && drawer) {
      drawer.close();
    }
  });
  if (drawer) drawer.addEventListener("click", (ev) => { if (ev.target === drawer) drawer.close(); }); // backdrop

  if (!bar) return;
  const day = () => Number(document.body.dataset.simDay || 0);
  const scrub = document.getElementById("sim-scrubber");

  async function demo(path, label) {
    try {
      await api(path, {method: "POST"});
      if (label) toast(label);
    } catch (err) {
      toast(err.message, {level: "urgent"});
    }
    await refresh();
    sync();
  }
  function to(n) {
    if (n < day()) {
      toast("Demo days only move forward. Press Reset to start over.");
      sync();
      return;
    }
    if (n === day()) return;
    demo(`/api/demo/advance?to_day=${n}`);
  }
  // Buttons for days already passed are disabled; the scrubber follows the clock.
  function sync() {
    const d = day();
    if (scrub && document.activeElement !== scrub) scrub.value = String(Math.min(d, Number(scrub.max)));
    bar.querySelectorAll("[data-jump]").forEach((b) => {
      b.disabled = Number(b.dataset.jump) < d;
      b.setAttribute("aria-pressed", String(Number(b.dataset.jump) === d));
    });
  }

  bar.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.advance) demo(`/api/demo/advance?days=${b.dataset.advance}`);
    else if (b.dataset.jump) to(Number(b.dataset.jump));
    else if (b.id === "toggle-fair-trial") demo(`/api/demo/toggle-fair-trial/${b.dataset.merchant}`, "Fair Trial membership toggled for Quillnote.");
    else if (b.id === "demo-reset" && confirm("Reset the demo? This wipes the runtime data.")) {
      api("/api/demo/reset", {method: "POST"}).then(() => location.reload()).catch((e) => toast(e.message, {level: "urgent"}));
    }
  });
  if (scrub) scrub.addEventListener("change", () => to(Number(scrub.value)));
  document.addEventListener("keydown", (ev) => {
    if (ev.key.toLowerCase() !== "d" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.target.closest("input, textarea, select, [contenteditable], dialog[open]")) return;
    bar.hidden = !bar.hidden;
    document.body.classList.toggle("has-presenter", !bar.hidden);
  });
  document.body.classList.toggle("has-presenter", !bar.hidden);

  // ---- the step indicator (B4) --------------------------------------------------------------------
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
  onRefresh(async () => {
    applySteps((await api(`/api/audit-log/summary?user=${window.SG.user}`)).steps);
    sync();
  });
  sync();
})();

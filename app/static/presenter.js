// Live demo controls (D-167, the page at /?demo=1; was the presenter bar, U6). Day scrubber (forward only), jumps to Day 0/5/6/7/11,
// +1 day, Reset, "Quillnote connected to SubGuard" (Fair Trial toggle), "See the full record", the 7-step indicator,
// and the landing section's "Play Priya's story" (D-173). The steps
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

  // Shared step helpers: set one step's state, and fill the rail up to the last step reached IN ORDER.
  window.SGSteps = {
    set(el, state, detail) {
      el.classList.remove("is-active", "is-done", "is-skipped", "is-warn");
      if (state) el.classList.add("is-" + state);
      const det = el.querySelector(".step-detail");
      if (state === "skipped") det.textContent = "skipped" + (detail ? `: ${detail}` : "");
      else if (detail != null) det.textContent = detail;
      const dot = el.querySelector(".step-dot");
      const k = Array.from(el.parentNode.children).indexOf(el);
      dot.textContent = state === "done" || state === "warn" ? "✓" : String(k + 1);
    },
    fill(els, rail) {
      let reached = 0;
      for (let k = 0; k < els.length; k++) {
        if (!els[k].matches(".is-active, .is-done, .is-warn, .is-skipped")) break;
        reached = k;
      }
      if (rail) rail.style.width = (reached / (els.length - 1)) * 100 + "%";
    },
  };

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
    else if (b.id === "toggle-fair-trial") toggleConnected(b);
    else if (b.id === "demo-reset" && confirm("Reset the demo? This wipes the runtime data.")) {
      api("/api/demo/reset", {method: "POST"}).then(() => location.reload()).catch((e) => toast(e.message, {level: "urgent"}));
    }
  });
  if (scrub) scrub.addEventListener("change", () => to(Number(scrub.value)));

  // "Quillnote connected to SubGuard: on/off" (the Fair Trial toggle, D-173): the label follows PayPal-side state.
  async function toggleConnected(b) {
    try {
      const r = await api(`/api/demo/toggle-fair-trial/${b.dataset.merchant}`, {method: "POST"});
      const on = Boolean(r.fair_trial_member);
      b.setAttribute("aria-pressed", String(on));
      b.querySelector(".js-ft").textContent = on ? "on" : "off";
      toast(on ? "Quillnote is now connected: SubGuard can cancel it in PayPal itself."
               : "Quillnote is not connected: Priya cancels with one tap in PayPal.");
    } catch (err) {
      toast(err.message, {level: "urgent"});
    }
    await refresh();
    sync();
  }

  // ---- the landing section (D-173): pressing "Play Priya's story" (the one start button) scrolls to the controls,
  // and "What is SubGuard?" takes you back to the hero.
  const run = document.getElementById("run-demo");
  const start = document.getElementById("demo-start");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function toControls() {
    if (run) run.open = true;
    bar.scrollIntoView({block: "start", behavior: reduce ? "auto" : "smooth"});
  }
  if (start) start.addEventListener("click", toControls);

  // ---- the step indicator (B4), shared with autoplay.js --------------------------------------------------------------------
  const stepEls = Array.from(document.querySelectorAll("#pipeline-steps .step"));
  const fill = document.getElementById("pipe-fill");
  // The tracker fills in order (D-173): a step shows its state only once every step before it has one.
  function applySteps(list) {
    if (!stepEls.length || !list) return;
    const byKey = Object.fromEntries(list.map((st) => [st.key, st]));
    for (const el of stepEls) {
      const st = byKey[el.dataset.step];
      if (!st || st.state === "pending") {
        if (!el.matches(".is-active, .is-done, .is-warn, .is-skipped")) break;  // autoplay owns it; stop here
        continue;
      }
      window.SGSteps.set(el, st.state, st.detail);
    }
    window.SGSteps.fill(stepEls, fill);
  }
  onRefresh(async () => {
    applySteps((await api(`/api/audit-log/summary?user=${window.SG.user}`)).steps);
    sync();
  });
  sync();
})();

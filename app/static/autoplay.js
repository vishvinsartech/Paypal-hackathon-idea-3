// "Start demo": runs Priya's story through the same APIs the UI uses, with an animated stepper. Mock mode does
// steps 1-2 here; sandbox mode opens a real Penwright window for them (autoplay_sandbox.js, D-116).
// Day 0 review -> PAUSE for the order confirmation (mock: the PayPal approval card here; sandbox: PayPal's window)
// -> safety timer -> days pass -> PAUSE at the check-in for Priya's choice (Keep / Cancel under Priya's side, or
// "Don't answer") -> the rest of the timeline to the first charge day. Everything else plays itself (D-168): after
// her Cancel tap the confirmation card confirms itself and her email is sent to the demo outbox. A cancel still
// goes through the confirmation card's token (R1/R3); nothing here bypasses the policy.
(function () {
  "use strict";
  const btn = document.getElementById("demo-start");
  if (!btn || btn.disabled || !window.SG) return;
  const {user, esc, api, toast, refresh} = window.SG;
  const steps = Array.from(document.querySelectorAll("#pipeline-steps .step"));
  const statusEl = document.getElementById("pipe-status");
  const fill = document.getElementById("pipe-fill");
  const doneBox = document.getElementById("pipe-done");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduce ? Math.min(ms, 120) : ms));
  const post = (path, body) => api(path, {method: "POST", body});

  // ---- stepper ------------------------------------------------------------------------------
  function mark(name, state, detail) {
    window.SGSteps.set(steps.find((s) => s.dataset.step === name), state, detail);
    window.SGSteps.fill(steps, fill);
  }
  function resetSteps() {
    steps.forEach((s, k) => {
      s.className = "step";
      s.querySelector(".step-dot").textContent = String(k + 1);
      const d = s.querySelector(".step-detail");
      d.textContent = d.dataset.hint;
    });
    fill.style.width = "0";
    doneBox.innerHTML = "";
  }
  function say(html) {
    statusEl.innerHTML = html;
    statusEl.classList.remove("is-new");
    void statusEl.offsetWidth; // restart the animation
    statusEl.classList.add("is-new");
  }
  async function toDay(n) {
    await post(`/api/demo/advance?to_day=${n}`);
    await refresh();
  }
  const subNow = async (id) => (await api(`/api/subscriptions?user=${user}`)).find((s) => s.id === id);
  const openCheckin = async (id) => (await api(`/api/alerts?user=${user}`))
    .find((a) => a.kind === "reminder" && a.subscription_id === id && !a.acknowledged_at);

  // ---- Priya's choice (U8, D-167): answered on the "Keep it or cancel?" band under Priya's side, the only Keep /
  // Cancel on screen. The story panel offers "Don't answer". We wait for the answer to land (and any dialog to close).
  const skipBtn = document.getElementById("decision-skip");
  async function decide(alert, fireText) {
    skipBtn.textContent = `Don't answer (SubGuard acts on ${fireText})`;
    skipBtn.hidden = false;
    let skipped = false;
    const onSkip = () => { skipped = true; };
    skipBtn.addEventListener("click", onSkip, {once: true});
    const band = document.querySelector("[data-testid=user-reminder]");
    if (band) band.scrollIntoView({block: "center", behavior: reduce ? "auto" : "smooth"});
    try {
      for (;;) {
        await sleep(400);
        if (document.querySelector("dialog[open]:not(#audit-drawer)")) continue;  // confirmation / email open
        if (skipped) return "skip";
        const a = (await api(`/api/alerts?user=${user}`)).find((x) => x.id === alert.id);
        if (a && a.acknowledged_at) {
          const s = await subNow(alert.subscription_id);
          if (s.status === "CANCELLED") return "cancel";
          if (s.kept_day != null) return "keep";
          return "cancel_failed"; // PayPal didn't confirm: shown as a toast, the timer stays in charge
        }
      }
    } finally {
      skipBtn.hidden = true;
      skipBtn.removeEventListener("click", onSkip);
    }
  }

  // The order confirmation (D-168): one of the two steps the demo leaves to a person. Resolves on "Agree".
  function confirmOrder(text) {
    const box = document.getElementById("order-confirm");
    const go = document.getElementById("order-approve");
    document.getElementById("order-text").textContent = text;
    box.hidden = false;
    box.scrollIntoView({block: "center", behavior: reduce ? "auto" : "smooth"});
    return new Promise((resolve) => go.addEventListener("click", () => { box.hidden = true; resolve(); }, {once: true}));
  }

  // Steps 1-2 in mock mode: the review, then the order confirmation (a simulated PayPal approval), all in this page.
  async function mockStart() {
    mark("read", "active", "reading…");
    say("<strong>Day 0.</strong> Priya clicks PayPal on Penwright. SubGuard reads the fine print first…");
    const pre = await post("/api/review/preflight", {merchant_url: "/shop/penwright", plan_key: "penwright-pro", user_id: user});
    await sleep(1400);
    mark("read", "done", `Risk ${pre.risk_score} · act by ${pre.display.points.act_by.date}`);  // same text as the derived step (B4)
    say(esc(pre.summary));
    await sleep(1600);

    mark("approve", "active", "confirm the order");
    const created = await post("/api/checkout/create", {merchant_id: "penwright", plan_key: "penwright-pro", user_id: user});
    say("<strong>Your turn: confirm the order.</strong> PayPal asks Priya to approve the trial " +
      "(simulated here; sandbox mode shows the real PayPal window).");
    const v = pre.display && pre.display.verdict;
    await confirmOrder(`Penwright Studio, Pro plan: ${v && v.line ? v.line : "free trial"}.`);
    mark("approve", "active", "PayPal…");
    await post("/api/checkout/mock-approve", {paypal_id: created.paypal_id});
    const sub = await post("/api/subscriptions/register", {paypal_id: created.paypal_id, merchant_id: "penwright",
      plan_key: "penwright-pro", user_id: user, review_id: pre.review_id});
    mark("approve", "done", `PayPal ${sub.status}`);
    return {pre, sub};
  }

  // ---- the run ---------------------------------------------------------------------------------
  async function run(win) {
    btn.disabled = true;
    btn.textContent = "Running…";
    resetSteps();
    say("Resetting the demo…");
    await post("/api/demo/reset");
    await refresh();
    const {pre, sub} = win ? await window.SGSandboxStart(win, {mark, say, esc, user}) : await mockStart();
    await refresh();
    const deadline = pre ? pre.deadlines.real_cancel_deadline_day : null;
    await sleep(900);

    mark("timer", "active");
    const timer = (await api(`/api/timers?user=${user}`)).find((t) => t.subscription_id === sub.id);
    await sleep(700);
    const checkDay = timer ? timer.reminder_day : null;
    const fireDay = timer ? timer.fire_day : null;
    mark("timer", timer ? "done" : "warn", timer ? null : "No auto-timer");  // dated detail comes from the derived steps
    say("<strong>“I'll check with you before your trial runs out.”</strong>");
    await sleep(1400);

    let alert = null;
    const lastQuiet = checkDay != null ? checkDay : deadline;
    mark("wait", "active");
    for (let d = 1; d <= lastQuiet && !alert; d++) {
      await toDay(d);
      mark("wait", "active", `Day ${d}`);
      say(`<strong>Day ${d}.</strong> ${d < lastQuiet ? "Priya uses the trial. SubGuard watches the clock." : "Check-in day."}`);
      alert = await openCheckin(sub.id);
      await sleep(alert ? 300 : 900);
    }
    mark("wait", "done", `${lastQuiet} days`);

    let choice = "none";
    if (alert) {
      mark("ask", "active", `Day ${alert.sim_day}`);
      say(`<strong>Day ${alert.sim_day}.</strong> SubGuard asks Priya by email, SMS and in-app. <strong>Your turn:</strong> answer for her under <strong>Priya's side</strong>, <strong>Keep</strong> or <strong>Cancel trial</strong>. The rest plays itself.`);
      await sleep(700);
      const row = (await api(`/api/view/subscriptions?user=${user}`)).rows.find((r) => r.id === sub.id);
      choice = await decide(alert, row && row.timer ? row.timer.fire_text : `Day ${fireDay}`);
      const said = {keep: "Priya: Keep", cancel: "Priya: Cancel", cancel_failed: "Cancel failed", skip: "No answer"}[choice];
      mark("ask", choice === "cancel_failed" ? "warn" : "done", null);
      say(esc(said));
    } else {
      mark("ask", "skipped", "no check-in day");
    }

    mark("outcome", "active");
    const billing = sub.next_billing_day != null ? sub.next_billing_day : lastQuiet + 10;
    let outcome = "";
    for (let d = lastQuiet + 1; d <= billing; d++) {
      await toDay(d);
      say(`<strong>Day ${d}.</strong>`);
      const s = await subNow(sub.id);
      if (!outcome && s.status === "CANCELLED") {
        outcome = s.cancelled_by === "timer" ? `Auto-cancelled Day ${s.cancelled_day} (R2)` : `Cancelled Day ${s.cancelled_day}`;
        mark("outcome", "done", null);
        say(`<strong>Day ${d}.</strong> Cancelled in PayPal. Priya won't be charged. ` + (s.cancelled_by === "timer"
          ? "Her cancellation email is drafted and waits for her to review and send it."
          : "Her cancellation email was drafted and sent to the demo outbox."));
        await sleep(1500);
      } else if (!outcome && choice === "keep") {
        outcome = "Kept";
        mark("outcome", "done", outcome);
      }
      await sleep(d === fireDay ? 1200 : 420);
    }
    if (!outcome) mark("outcome", "warn", "Still active");

    mark("proof", "active");
    const final = await subNow(sub.id);
    const kpi = await api(`/api/kpis?user=${user}`);
    await sleep(600);
    if (final.status === "CANCELLED") {
      mark("proof", "done", "Checked PayPal: no charge");
      say(`<strong>Day ${billing}.</strong> First charge due today. Checked PayPal: no active subscription, so no charge can be taken.`);
      doneBox.innerHTML = `<p class="pipe-done pipe-saved" data-testid="pipeline-done"><span class="saved-seal" aria-hidden="true">✓</span><span><strong>${esc(kpi.charges_avoided_text)} charge never taken</strong> (${esc(kpi.year_one_text)}). Every step is in the full record.</span></p>`;
      await refresh();
      window.SG.celebrate(doneBox.querySelector(".pipe-done"), kpi.charges_avoided_text);
      window.SG.celebrate(document.getElementById("live-kpis"), null);
    } else {
      const row = (await api(`/api/view/subscriptions?user=${user}`)).rows.find((r) => r.id === sub.id);
      mark("proof", "warn", null);
      say(`<strong>Day ${billing}.</strong> Priya kept Penwright, so the first charge goes through as she agreed.`);
      doneBox.innerHTML = `<p class="pipe-done" data-testid="pipeline-done">Kept on purpose: Penwright charges <strong>${esc(row ? row.price_text : "")}</strong> from today, and SubGuard won't ask again.</p>`;
    }
  }

  btn.addEventListener("click", async () => {
    // Sandbox: open the Penwright window now, inside the click, or the browser blocks it as a pop-up.
    const win = btn.dataset.sandbox ? window.open("about:blank", "penwright-demo", "popup,width=1180,height=900") : null;
    if (btn.dataset.sandbox && !win) {
      say("Your browser blocked the Penwright window. Allow pop-ups for this page, then press Play Priya's story again.");
      return;
    }
    document.body.dataset.autoplay = "1";
    try {
      await run(win);
    } catch (err) {
      if (win && !win.closed) win.close();
      document.getElementById("order-confirm").hidden = true;
      say(`The demo stopped: ${esc(err.message)}`);
      toast(err.message, {level: "urgent"});
    } finally {
      await refresh();
      delete document.body.dataset.autoplay;
      btn.disabled = false;
      btn.innerHTML = "&#8635; Run again";
    }
  });
})();

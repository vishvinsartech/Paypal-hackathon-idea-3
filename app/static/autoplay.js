// "Start demo": runs Priya's story through the same APIs the UI uses (mock mode), with an animated stepper.
// Day 0 review -> PayPal approval -> safety timer -> days pass -> PAUSE at the check-in for Priya's choice
// (Keep / Cancel / don't answer) -> the rest of the timeline to the first charge day.
// A cancel still needs the confirmation card's tap (R1/R3); nothing here bypasses the policy.
(function () {
  "use strict";
  const btn = document.getElementById("demo-start");
  if (!btn || btn.disabled || !window.SG) return;
  const {user, esc, api, toast, refresh, confirmInDialog} = window.SG;
  const steps = Array.from(document.querySelectorAll("#pipeline-steps .step"));
  const statusEl = document.getElementById("pipe-status");
  const fill = document.getElementById("pipe-fill");
  const doneBox = document.getElementById("pipe-done");
  const dlg = document.getElementById("decision-dialog");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduce ? Math.min(ms, 120) : ms));
  const post = (path, body) => api(path, {method: "POST", body});

  // ---- stepper ------------------------------------------------------------------------------
  function mark(name, state, detail) {
    const i = steps.findIndex((s) => s.dataset.step === name);
    const el = steps[i];
    el.classList.remove("is-active", "is-done", "is-skipped", "is-warn");
    if (state) el.classList.add("is-" + state);
    if (detail != null) el.querySelector(".step-detail").textContent = detail;
    if (state === "done" || state === "warn" || state === "skipped") el.querySelector(".step-dot").textContent = state === "skipped" ? "–" : "✓";
    const reached = steps.reduce((n, s, k) => (s.matches(".is-active, .is-done, .is-warn, .is-skipped") ? k : n), 0);
    fill.style.width = (reached / (steps.length - 1)) * 100 + "%";
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

  // ---- Priya's choice --------------------------------------------------------------------------
  function ask(alert, fireDay) {
    document.getElementById("decision-title").textContent = alert.title;
    document.getElementById("decision-body").textContent = alert.body;
    dlg.querySelector("[data-choice=skip]").textContent = `Don't answer (SubGuard acts on Day ${fireDay})`;
    dlg.showModal();
    dlg.querySelector("[data-choice=keep]").focus();
    return new Promise((resolve) => {
      const onClick = (ev) => {
        const b = ev.target.closest("[data-choice]");
        if (!b) return;
        dlg.removeEventListener("click", onClick);
        dlg.close();
        resolve(b.dataset.choice);
      };
      dlg.addEventListener("click", onClick);
    });
  }
  dlg.addEventListener("cancel", (ev) => ev.preventDefault()); // Escape doesn't count as an answer

  async function decide(alert, fireDay) {
    for (;;) {
      const choice = await ask(alert, fireDay);
      if (choice === "skip") return "skip";
      if (choice === "keep") {
        const out = await post(`/api/alerts/${alert.id}/act`, {user_id: user, action: "keep"});
        toast(out.message);
        return "keep";
      }
      const out = await post(`/api/alerts/${alert.id}/act`, {user_id: user, action: "cancel"});
      const res = out.confirm ? await confirmInDialog(out.confirm) : null;
      if (res && res.all_ok) return "cancel";
      if (res) return "cancel_failed"; // PayPal didn't confirm: shown as a toast, the timer stays in charge
      // "Not now" on the confirmation card: ask again
    }
  }

  // ---- the run ---------------------------------------------------------------------------------
  async function run() {
    btn.disabled = true;
    btn.textContent = "Running…";
    resetSteps();
    say("Resetting the demo…");
    await post("/api/demo/reset");
    await refresh();

    mark("read", "active", "reading…");
    say("<strong>Day 0.</strong> Priya clicks PayPal on Penwright. SubGuard reads the fine print first…");
    const pre = await post("/api/review/preflight", {merchant_url: "/shop/penwright", plan_key: "penwright-pro", user_id: user});
    await sleep(1400);
    const deadline = pre.deadlines.real_cancel_deadline_day;
    mark("read", "done", `Risk ${pre.risk_score} · cancel by Day ${deadline}`);
    say(esc(pre.summary));
    await sleep(1600);

    mark("approve", "active", "PayPal…");
    say("Priya approves the trial (mock PayPal approval; sandbox mode shows the real PayPal window).");
    const created = await post("/api/checkout/create", {merchant_id: "penwright", plan_key: "penwright-pro", user_id: user});
    await post("/api/checkout/mock-approve", {paypal_id: created.paypal_id});
    const sub = await post("/api/subscriptions/register", {paypal_id: created.paypal_id, merchant_id: "penwright",
      plan_key: "penwright-pro", user_id: user, review_id: pre.review_id});
    await refresh();
    mark("approve", "done", `PayPal ${sub.status}`);
    await sleep(900);

    mark("timer", "active");
    const timer = (await api(`/api/timers?user=${user}`)).find((t) => t.subscription_id === sub.id);
    await sleep(700);
    const checkDay = timer ? timer.reminder_day : null;
    const fireDay = timer ? timer.fire_day : null;
    mark("timer", timer ? "done" : "warn", timer ? `Ask Day ${checkDay} · cancel Day ${fireDay}` : "No auto-timer");
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
    mark("wait", "done", `Days 1-${lastQuiet}`);

    let choice = "none";
    if (alert) {
      mark("ask", "active", `Day ${alert.sim_day}`);
      say(`<strong>Day ${alert.sim_day}.</strong> SubGuard asks Priya by email, SMS and in-app. Waiting for her answer…`);
      await sleep(700);
      choice = await decide(alert, fireDay);
      const said = {keep: "Priya: Keep", cancel: "Priya: Cancel", cancel_failed: "Cancel failed", skip: "No answer"}[choice];
      mark("ask", choice === "cancel_failed" ? "warn" : "done", said);
    } else {
      mark("ask", "skipped", "no check-in");
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
        mark("outcome", "done", outcome);
        say(`<strong>Day ${d}.</strong> Cancelled in PayPal. Priya won't be charged. ` + (s.cancelled_by === "timer"
          ? "Her cancellation email is drafted and waits for her to review and send it."
          : "Her cancellation email was drafted for her to review and send."));
        await sleep(1500);
      } else if (!outcome && choice === "keep") {
        outcome = "Kept · no more prompts";
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
      mark("proof", "done", `Day ${billing}: charge blocked`);
      say(`<strong>Day ${billing}.</strong> First charge due today: blocked. No active PayPal subscription.`);
      doneBox.innerHTML = `<p class="pipe-done" data-testid="pipeline-done"><strong>${esc(kpi.money_protected_text)}</strong> kept in Priya's pocket this year. Every step is in the audit log below.</p>`;
    } else {
      const row = (await api(`/api/view/subscriptions?user=${user}`)).rows.find((r) => r.id === sub.id);
      mark("proof", "warn", `Day ${billing}: charged`);
      say(`<strong>Day ${billing}.</strong> Priya kept Penwright, so the first charge goes through as she agreed.`);
      doneBox.innerHTML = `<p class="pipe-done" data-testid="pipeline-done">Kept on purpose: Penwright charges <strong>${esc(row ? row.price_text : "")}</strong> from today, and SubGuard won't ask again.</p>`;
    }
  }

  btn.addEventListener("click", async () => {
    try {
      await run();
    } catch (err) {
      say(`The demo stopped: ${esc(err.message)}`);
      toast(err.message, {level: "urgent"});
    } finally {
      await refresh();
      btn.disabled = false;
      btn.innerHTML = "&#8635; Run again";
    }
  });
})();

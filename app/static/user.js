// Priya's dashboard (/user, D-110/D-112): the subscription card and the Day 5 check-in buttons, plus the live refresh.
// Cancel flow (same everywhere): Cancel -> confirmation card (R1/R3) -> email preview. No extra pop-ups.
(function () {
  "use strict";
  if (!window.SG) return;
  const {user, api, toast, refresh, confirmInDialog, proposeCancel} = window.SG;

  async function act(path, body, btn) {
    btn.disabled = true;
    try {
      return await api(path, {method: "POST", body});
    } catch (err) {
      toast(err.message, {level: "urgent"});
      return null;
    } finally {
      btn.disabled = false;
    }
  }

  document.addEventListener("click", async (ev) => {
    const keep = ev.target.closest("[data-sub-keep]");
    const cancel = ev.target.closest("[data-sub-cancel]");
    const alertBtn = ev.target.closest("[data-alert][data-action]");
    if (keep) {
      const out = await act(`/api/subscriptions/${keep.dataset.subKeep}/keep`, {user_id: user}, keep);
      if (out) toast(out.message);
    } else if (cancel) {
      await proposeCancel([cancel.dataset.subCancel], "Cancelled from your dashboard");
    } else if (alertBtn) {
      const out = await act(`/api/alerts/${alertBtn.dataset.alert}/act`, {user_id: user, action: alertBtn.dataset.action}, alertBtn);
      if (out && out.confirm) await confirmInDialog(out.confirm);
      else if (out && out.message) toast(out.message);
    } else {
      return;
    }
    await tick(true);
  });

  // Live: the demo may run in another tab. Swap only the server-rendered [data-live] sections that changed, then
  // refresh the AG Grid activity list and the AG Charts through their APIs (they are never re-created).
  async function tick(force) {
    if (!force && (document.hidden || document.querySelector("dialog[open]"))) return;
    try {
      const html = await (await fetch(location.href, {headers: {Accept: "text/html"}})).text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      document.querySelectorAll("[data-live]").forEach((el) => {
        const fresh = doc.getElementById(el.id);
        if (!fresh || fresh.innerHTML === el.innerHTML) return;
        const open = new Set([...el.querySelectorAll("details[open] summary")].map((s) => s.textContent));
        el.innerHTML = fresh.innerHTML;
        el.hidden = fresh.hidden;
        el.querySelectorAll("details summary").forEach((s) => { if (open.has(s.textContent)) s.parentElement.open = true; });
      });
      await refresh();
    } catch (e) { /* offline for a moment: try again next tick */ }
  }
  refresh();
  setInterval(() => tick(false), 4000);
})();

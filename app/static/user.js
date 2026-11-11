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

  // Key dates (D-115): the server renders UTC text; show each <time data-local> in the viewer's own time zone.
  const DATE = {weekday: "short", day: "numeric", month: "short", year: "numeric"};
  const DATETIME = {...DATE, hour: "2-digit", minute: "2-digit", timeZoneName: "short"};
  function localize(root) {
    root.querySelectorAll("time[data-local]").forEach((t) => {
      const d = new Date(t.getAttribute("datetime"));
      if (isNaN(d)) return;
      t.textContent = d.toLocaleString(undefined, t.dataset.local === "datetime" ? DATETIME : DATE);
      t.title = d.toISOString();
    });
  }
  const served = new WeakMap(); // [data-live] element -> the server HTML it last showed
  document.querySelectorAll("[data-live]").forEach((el) => served.set(el, el.innerHTML));
  localize(document);

  // Live: the demo may run in another tab. Swap only the server-rendered [data-live] sections that changed, then
  // refresh the AG Grid activity list and the AG Charts through their APIs (they are never re-created).
  async function tick(force) {
    if (!force && (document.hidden || document.querySelector("dialog[open]"))) return;
    try {
      const url = new URL(location.href);
      url.searchParams.set("live", "1"); // marks the background refresh, so the terminal log can skip it
      const html = await (await fetch(url, {headers: {Accept: "text/html"}})).text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      document.querySelectorAll("[data-live]").forEach((el) => {
        const fresh = doc.getElementById(el.id);
        // Compare server HTML with server HTML: the visible copy has localized dates.
        if (!fresh || fresh.innerHTML === served.get(el)) return;
        served.set(el, fresh.innerHTML);
        const open = new Set([...el.querySelectorAll("details[open] summary")].map((s) => s.textContent));
        el.innerHTML = fresh.innerHTML;
        el.hidden = fresh.hidden;
        el.querySelectorAll("details summary").forEach((s) => { if (open.has(s.textContent)) s.parentElement.open = true; });
        localize(el);
      });
      await refresh();
    } catch (e) { /* offline for a moment: try again next tick */ }
  }
  refresh();
  setInterval(() => tick(false), 4000);
})();

// Priya's SubGuard at `/` (U5-U12, D-148): card actions, the live refresh, toasts for new alerts, the PayPal
// footer, the count-up, and Layer 2 polling. Cancel flow everywhere: Cancel -> confirmation card (R1/R3) ->
// email preview. The server renders every number and date; this file only swaps HTML and animates.
// U29: <html data-ready="1"> once the page is settled (no count-up running), so the video recorder can wait for it.
(function () {
  "use strict";
  if (!window.SG) return;
  const {user, api, toast, onRefresh, refresh, confirmInDialog, proposeCancel} = window.SG;
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let animating = 0;
  const settle = () => { root.dataset.ready = animating ? "0" : "1"; };

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
      await proposeCancel([cancel.dataset.subCancel], "Cancelled on your SubGuard card");
    } else if (alertBtn) {
      const out = await act(`/api/alerts/${alertBtn.dataset.alert}/act`, {user_id: user, action: alertBtn.dataset.action}, alertBtn);
      if (out && out.confirm) await confirmInDialog(out.confirm);
      else if (out && out.message) toast(out.message);
    } else {
      return;
    }
    await refresh();
  });

  // ---- dates in the viewer's time zone (D-115) -----------------------------------------------------
  const DATE = {weekday: "short", day: "numeric", month: "short", year: "numeric"};
  const DATETIME = {...DATE, hour: "2-digit", minute: "2-digit", timeZoneName: "short"};
  function localize(el) {
    el.querySelectorAll("time[data-local]").forEach((t) => {
      const d = new Date(t.getAttribute("datetime"));
      if (isNaN(d)) return;
      t.textContent = d.toLocaleString(undefined, t.dataset.local === "datetime" ? DATETIME : DATE);
      t.title = d.toISOString();
    });
  }

  // ---- count-up (U29): numbers animate when they change; the page reports ready when done -------------
  function countUp(el, from) {
    const text = el.textContent;
    const m = text.match(/^([^\d-]*)(-?[\d,]*\.?\d+)(.*)$/s);
    const card = el.closest(".kpi");
    if (card) { card.classList.remove("is-bumped"); void card.offsetWidth; card.classList.add("is-bumped"); }
    if (!m || reduce || from === null) return;
    const [, pre, num, post] = m;
    const to = parseFloat(num.replace(/,/g, ""));
    if (to === from) return;
    const decimals = (num.split(".")[1] || "").length;
    const fmt = (v) => pre + v.toLocaleString("en-US", {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) + post;
    const start = performance.now();
    animating++;
    settle();
    (function frame(now) {
      const t = Math.min(1, (now - start) / 900);
      el.textContent = t < 1 ? fmt(from + (to - from) * (1 - Math.pow(1 - t, 3))) : text;
      if (t < 1) requestAnimationFrame(frame);
      else { animating--; settle(); }
    })(start);
  }
  const numberIn = (el) => {
    const m = el && el.textContent.match(/-?[\d,]*\.?\d+/);
    return m ? parseFloat(m[0].replace(/,/g, "")) : null;
  };

  // ---- the PayPal footer on each card (U7): read live from PayPal when opened, re-read on status change --
  const ppRead = new Map(); // subscription id -> our status when last read
  function paypalFooters(force) {
    document.querySelectorAll("[data-pp-sub]").forEach((d) => {
      const body = d.querySelector("[data-pp-body]");
      if (!d.open || !body || !window.PayPalCard) return;
      if (!force && ppRead.get(d.dataset.ppSub) === d.dataset.ppStatus && body.innerHTML) return;
      ppRead.set(d.dataset.ppSub, d.dataset.ppStatus);
      window.PayPalCard.mount(body, d.dataset.ppSub, user, "lite");
    });
  }
  document.addEventListener("toggle", (ev) => { if (ev.target.matches && ev.target.matches("[data-pp-sub]")) paypalFooters(true); }, true);

  // ---- live refresh: swap only the server-rendered [data-live] parts that changed ------------------------
  const served = new WeakMap(); // [data-live] element -> the server HTML it last showed
  document.querySelectorAll("[data-live]").forEach((el) => served.set(el, el.innerHTML));
  localize(document);
  let chain = Promise.resolve();  // swaps run one after another, so an action's refresh is never skipped

  async function doSwap() {
    if (document.hidden) return;
    try {
      const url = new URL(location.href);
      url.searchParams.set("live", "1"); // marks the background refresh, so the terminal log can skip it
      const html = await (await fetch(url, {headers: {Accept: "text/html"}})).text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      document.querySelectorAll("[data-live]").forEach((el) => {
        const fresh = doc.getElementById(el.id);
        if (!fresh || fresh.innerHTML === served.get(el)) return;  // compare server HTML with server HTML
        served.set(el, fresh.innerHTML);
        const open = new Set([...el.querySelectorAll("details[open]")].map((d) => d.dataset.ppSub || d.querySelector("summary")?.textContent));
        const before = numberIn(el.querySelector("[data-countup]"));
        el.innerHTML = fresh.innerHTML;
        el.hidden = fresh.hidden;
        el.querySelectorAll("details").forEach((d) => {
          if (open.has(d.dataset.ppSub || d.querySelector("summary")?.textContent)) d.open = true;
        });
        localize(el);
        const counter = el.querySelector("[data-countup]");
        if (counter) countUp(counter, before);
      });
      const side = document.getElementById("home-side");
      const freshSide = doc.getElementById("home-side");
      if (side && freshSide) side.hidden = freshSide.hidden;
      document.querySelectorAll(".js-day").forEach((el) => {
        const day = doc.body.dataset.simDay;
        if (day == null || el.textContent === day) return;
        el.textContent = day;
        el.classList.remove("day-bump"); void el.offsetWidth; el.classList.add("day-bump");
      });
      document.body.dataset.simDay = doc.body.dataset.simDay;
      paypalFooters(false);
    } catch (e) { /* offline for a moment: try again next tick */ }
  }
  const swap = () => (chain = chain.then(doSwap));
  onRefresh(swap);

  // ---- toasts for new alerts (B5) -----------------------------------------------------------------------
  // The cancel flow (Cancel -> confirmation -> email preview) already says "Cancelled in PayPal": not toasted.
  const QUIET = new Set(["cancelled"]);
  let seen = null; // alert ids already shown; null until the first load (no toasts on page load)
  onRefresh(async () => {
    const alerts = await api(`/api/alerts?user=${user}`);
    if (seen !== null) {
      alerts.filter((a) => !seen.has(a.id) && !QUIET.has(a.kind)).reverse().forEach((a) =>
        toast(a.body, {title: a.title, level: a.level, testid: "toast-alert"}));
    }
    seen = new Set(alerts.map((a) => a.id));
  });

  // ---- A5 (Layer 2): while an ACTION NEEDED band is up, ask SubGuard to read PayPal (read-only GET) ---------
  let checking = false;
  async function pollLayer2() {
    const ids = [...new Set([...document.querySelectorAll("[data-poll-sub]")].map((el) => el.dataset.pollSub))];
    if (!ids.length || checking || document.hidden) return;
    checking = true;
    try {
      for (const id of ids) {
        const out = await api(`/api/subscriptions/${id}/check-paypal?user=${user}`, {method: "POST", body: {}});
        if (out && out.cancelled) {
          toast("PayPal shows it CANCELLED. You won't be charged.", {title: "Checked PayPal", testid: "toast-layer2"});
          await refresh();
        }
      }
    } catch (e) { /* PayPal or the network hiccuped: try again next round */ }
    checking = false;
  }

  document.addEventListener("DOMContentLoaded", () => { refresh().then(settle); });  // after every script registered (B3)
  setInterval(() => { if (!document.hidden && !document.querySelector("dialog[open]:not(#audit-drawer)")) refresh(); }, 4000);
  setInterval(pollLayer2, 3000);
  settle();
})();

// Priya's sections (D-174): Overview · Subscriptions (In use / Trials / Cancelled) · Activity · Emails · Analytics ·
// Settings, one at a time. A left sidebar on desktop, a bottom bar on phones (home.css / dashboard.css); the same
// <nav>. The URL hash names the section and filter (#subscriptions/trial), so reloads and links keep it.
// Old hashes (#history, #messages) land on Activity.
(function () {
  "use strict";
  // ---- every page (D-182): demo-only controls carry data-soon. One toast, nothing else happens (R7). ----------
  document.addEventListener("click", (ev) => {
    const soon = ev.target.closest("[data-soon]");
    if (soon) {
      ev.preventDefault();
      if (window.SG) window.SG.toast("Not part of this demo", {testid: "toast-soon"});
      return;
    }
    const menu = ev.target.closest(".avatar-menu .menu-body a, .avatar-menu [data-help]");
    if (menu) menu.closest("details").open = false;
    if (ev.target.closest(".avatar-menu [data-help]")) {  // Help: Ask SubGuard answers questions about the demo
      const chat = document.getElementById("chat-open");
      if (chat) chat.click();
    }
  });

  const nav = document.querySelector("[data-testid=side-nav]");
  if (!nav) return;
  const links = Array.from(nav.querySelectorAll("[data-nav]"));
  const panels = Array.from(document.querySelectorAll("[data-panel]"));
  const names = new Set(panels.map((p) => p.dataset.panel));
  const OLD = {history: "activity", messages: "activity"};
  const FILTERS = new Set(["all", "in_use", "trial", "cancelled"]);
  function pick() {
    const [h, f] = location.hash.slice(1).split("/");
    const n = OLD[h] || h;
    return {name: names.has(n) ? n : "overview", filter: FILTERS.has(f) ? f : "all"};
  }

  // ---- the Subscriptions list's filter (chips and the sidebar's sub-items) ----------------------------
  let filter = "all";
  function applyFilter() {
    const rows = Array.from(document.querySelectorAll("#live-subs-list [data-group]"));
    rows.forEach((r) => { r.hidden = filter !== "all" && r.dataset.group !== filter; });
    const empty = document.querySelector("[data-testid=subs-empty]");
    if (empty) empty.hidden = rows.some((r) => !r.hidden);
    document.querySelectorAll(".sl-filters [data-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === filter)));
  }

  function show(name, f, focus) {
    filter = f || "all";
    panels.forEach((p) => { p.hidden = p.dataset.panel !== name; });
    links.forEach((a) => {  // a section is current; a sub-item only when its filter is on
      const on = a.dataset.filter ? name === "subscriptions" && a.dataset.filter === filter : a.dataset.nav === name;
      if (on) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
    applyFilter();
    window.dispatchEvent(new Event("resize")); // grids and charts measure themselves when they become visible
    document.dispatchEvent(new CustomEvent("sg-section", {detail: name}));
    if (focus) {
      const panel = panels.find((p) => p.dataset.panel === name);
      const h = panel && panel.querySelector("h2");
      if (h) { h.setAttribute("tabindex", "-1"); h.focus({preventScroll: true}); }
      window.scrollTo({top: 0});
    }
  }
  function go(name, f) {
    history.replaceState(null, "", `#${name}${f && f !== "all" ? "/" + f : ""}`);
    show(name, f, true);
  }

  nav.addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-nav]");
    if (!a) return;
    ev.preventDefault();
    go(a.dataset.nav, a.dataset.filter);
  });
  document.addEventListener("click", (ev) => {
    const chip = ev.target.closest(".sl-filters [data-filter]");
    if (chip) go("subscriptions", chip.dataset.filter);
    const jump = ev.target.closest("a[data-go]");  // e.g. the card's "Change plan" -> Settings (D-177)
    if (jump && names.has(jump.dataset.go)) { ev.preventDefault(); go(jump.dataset.go); return; }
    const see = ev.target.closest('a[href="#activity"]');
    if (see && !nav.contains(see)) { ev.preventDefault(); go("activity"); }
  });
  window.addEventListener("hashchange", () => { const p = pick(); show(p.name, p.filter, false); });
  const first = pick();
  show(first.name, first.filter, false);
  // the live refresh swaps the list's rows; keep the filter on them
  new MutationObserver(applyFilter).observe(document.getElementById("live-subs-list") || document.body, {childList: true});

  // ---- the sidebar folds to a 56 px icon strip. The choice is remembered; below 1100 px it starts folded
  // (the inline script in home.html sets <html data-side> before first paint, so there's no jump). --------------
  const toggle = document.getElementById("side-toggle");
  if (toggle) {
    const root = document.documentElement;
    const narrow = window.matchMedia("(max-width: 1099px)");
    const setFolded = (folded, save) => {
      if (folded) root.dataset.side = "folded"; else delete root.dataset.side;
      const label = folded ? "Expand sidebar" : "Collapse sidebar";
      toggle.setAttribute("aria-expanded", String(!folded));
      toggle.setAttribute("aria-label", label);
      toggle.dataset.tip = label;
      toggle.querySelector(".nav-label").textContent = label;
      if (save) { try { localStorage.setItem("sg-side", folded ? "folded" : "open"); } catch (e) { /* private mode */ } }
      window.dispatchEvent(new Event("resize")); // grids and charts re-measure
    };
    setFolded(root.dataset.side === "folded", false);
    toggle.addEventListener("click", () => setFolded(root.dataset.side !== "folded", true));
    narrow.addEventListener("change", (e) => { if (e.matches) setFolded(true, false); });
  }

  // ---- Settings: saved on every change (POST /api/settings, audited) -------------------------------
  const form = document.getElementById("settings-form");
  const status = document.getElementById("settings-status");
  if (form && window.SG) {
    form.addEventListener("change", async () => {
      const body = {user_id: window.SG.user, auto_cancel_trials: form.auto_cancel_trials.checked,
                    auto_send_notice: form.auto_send_notice.checked, remind_by_email: form.remind_by_email.checked};
      try {
        await window.SG.api("/api/settings", {method: "POST", body});
        status.textContent = "Saved.";
      } catch (err) {
        status.textContent = "";
        window.SG.toast(err.message, {level: "urgent"});
      }
    });
  }
})();

// Priya's sections (U10): Overview · Activity · Emails, one at a time. Tabs on desktop, a bottom tab bar on
// mobile (B9, U27); the same <nav>, styled by home.css. The URL hash names the section (#activity), so reloads and
// links keep it. Old hashes (#history, #messages, #analytics) land on Activity.
(function () {
  "use strict";
  const nav = document.querySelector("[data-testid=side-nav]");
  if (!nav) return;
  const links = Array.from(nav.querySelectorAll("[data-nav]"));
  const panels = Array.from(document.querySelectorAll("[data-panel]"));
  const names = new Set(panels.map((p) => p.dataset.panel));
  const OLD = {history: "activity", messages: "activity", analytics: "activity"};
  const pick = () => { const h = location.hash.slice(1); const n = OLD[h] || h; return names.has(n) ? n : "overview"; };

  function show(name, focus) {
    panels.forEach((p) => { p.hidden = p.dataset.panel !== name; });
    links.forEach((a) => {
      if (a.dataset.nav === name) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
    window.dispatchEvent(new Event("resize")); // grids measure themselves when they become visible
    if (focus) {
      const panel = panels.find((p) => p.dataset.panel === name);
      const h = panel && panel.querySelector("h2");
      if (h) { h.setAttribute("tabindex", "-1"); h.focus({preventScroll: true}); }
      if (nav.getBoundingClientRect().top < 0) nav.scrollIntoView({block: "start"});
    }
  }

  nav.addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-nav]");
    if (!a) return;
    ev.preventDefault();
    history.replaceState(null, "", `#${a.dataset.nav}`);
    show(a.dataset.nav, true);
  });
  window.addEventListener("hashchange", () => show(pick(), false));
  show(pick(), false);
})();

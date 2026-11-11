// Priya's dashboard sidebar (D-122): shows one section at a time (Overview, Analytics, History, Messages, Emails).
// The URL hash names the section (#analytics), so reloads and links keep it. The check-in, "email ready" and the
// Day 11 proof banner sit above the sections and are always visible.
(function () {
  "use strict";
  const nav = document.querySelector("[data-testid=side-nav]");
  if (!nav) return;
  const links = Array.from(nav.querySelectorAll("[data-nav]"));
  const panels = Array.from(document.querySelectorAll("[data-panel]"));
  const names = new Set(panels.map((p) => p.dataset.panel));
  const pick = () => { const h = location.hash.slice(1); return names.has(h) ? h : "overview"; };

  function show(name, focus) {
    panels.forEach((p) => { p.hidden = p.dataset.panel !== name; });
    links.forEach((a) => {
      if (a.dataset.nav === name) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
    // Charts and grids measure themselves when they become visible; nudge any that missed it.
    window.dispatchEvent(new Event("resize"));
    if (focus) {
      const panel = panels.find((p) => p.dataset.panel === name);
      const h = panel && panel.querySelector("h2");
      if (h) { h.setAttribute("tabindex", "-1"); h.focus({preventScroll: true}); }
      const top = document.getElementById("dash").getBoundingClientRect().top;
      if (top < 0) document.getElementById("dash").scrollIntoView({block: "start"});
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

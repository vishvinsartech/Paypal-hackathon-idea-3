// Evidence page `/subscriptions/{id}` (U23): four tabs (Summary · Evidence · PayPal check · Activity), the merchant
// page preview with the quoted elements outlined, and the full PayPal card (every id) on the PayPal tab.
(function () {
  "use strict";
  const tabs = Array.from(document.querySelectorAll("[data-ev-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-ev-panel]"));
  if (!tabs.length) return;
  const user = document.body.dataset.user || "priya";

  function show(key, focus) {
    tabs.forEach((t) => {
      const on = t.dataset.evTab === key;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    });
    panels.forEach((p) => { p.hidden = p.dataset.evPanel !== key; });
    if (location.hash.slice(1) !== key) history.replaceState(null, "", "#" + key);
    window.dispatchEvent(new Event("resize")); // grids and charts measure themselves when visible
    const pp = document.querySelector(`[data-ev-panel="${key}"] [data-pp-full]`);
    if (pp && !pp.innerHTML && window.PayPalCard) window.PayPalCard.mount(pp, pp.dataset.ppFull, user, "full");
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => show(t.dataset.evTab, false));
    t.addEventListener("keydown", (e) => {  // WAI-ARIA tabs: arrows move between tabs
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!d) return;
      e.preventDefault();
      show(tabs[(i + d + tabs.length) % tabs.length].dataset.evTab, true);
    });
  });
  const start = location.hash.slice(1);
  show(tabs.some((t) => t.dataset.evTab === start) ? start : "summary", false);

  const frame = document.getElementById("evidence");
  if (frame) {
    frame.addEventListener("load", () => {
      const doc = frame.contentDocument;
      if (!doc) return;
      for (const id of (frame.dataset.evidence || "").split(",").filter(Boolean)) {
        doc.querySelectorAll(`[data-testid="${CSS.escape(id)}"]`).forEach((el) => {
          el.style.outline = "3px solid #ff5a5f";
          el.style.outlineOffset = "2px";
          if (el.tagName === "DETAILS") el.open = true;
        });
      }
    });
  }
})();

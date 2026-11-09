// SubGuard dashboard: health dots, user switcher. (Grids, chat and demo controls come later.)
(function () {
  "use strict";

  async function loadHealth() {
    const el = document.getElementById("health");
    if (!el) return;
    try {
      const res = await fetch("/healthz");
      const data = await res.json();
      el.innerHTML = "";
      for (const [name, info] of Object.entries(data.integrations)) {
        const dot = document.createElement("span");
        dot.className = "dot " + info.state;
        dot.title = name + ": " + info.state;
        dot.setAttribute("role", "img");
        dot.setAttribute("aria-label", name + " " + info.state);
        el.appendChild(dot);
      }
    } catch (err) {
      el.textContent = "health unavailable";
    }
  }

  const switcher = document.getElementById("user-switch");
  if (switcher) {
    switcher.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("user", switcher.value);
      window.location.href = url.toString();
    });
  }

  loadHealth();
})();

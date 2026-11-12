// SubGuard video stage (D-184). SG.init(data) once, then SG.seek(t) per frame: everything on screen is a pure
// function of t, so record_stage.py can step frame by frame. seek() returns a key that only changes when the
// picture changes (record_stage.py reuses the last screenshot while the key stays the same).
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const clamp = (x) => Math.max(0, Math.min(1, x));
  const ease = (p) => p * p * (3 - 2 * p);
  const SHOW = {title: "flex", end: "flex", problem: "grid", cost: "flex", how: "block", pillars: "grid"};
  const IN = 0.4;     // fade/slide-in seconds for slides, cues and the frame
  const WORD = 0.16;  // a headline word's reveal
  const OUT = 0.35;   // an old headline chunk scrolling away
  let D = null;
  let drawn = {slot: null, chunk: -1};
  let anim = false;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  }
  function wordsHtml(chunk) {
    return chunk.map((w, i) => `<span class="w${w.a ? " a" : ""}" data-i="${i}">${esc(w.w)}${i < chunk.length - 1 ? " " : ""}</span>`).join("");
  }
  function fade(el, p, dy) {
    if (p > 0 && p < 1) anim = true;
    el.style.opacity = String(ease(p));
    el.style.transform = dy ? `translateY(${(1 - ease(p)) * dy}px)` : "";
  }

  function init(data) {
    D = data;
    document.body.classList.toggle("preview", !!data.preview);
    document.querySelectorAll("[data-fact]").forEach((el) => { el.textContent = data.facts[el.dataset.fact] ?? "?"; });
    document.querySelectorAll("[data-link]").forEach((el) => {
      const v = data.links[el.dataset.link] || "";
      el.textContent = v;
      el.hidden = !v;
    });
    $("pill-text").textContent = data.pill;
    const width = 1720 - 10 * (data.chapters.length - 1);
    $("progress").innerHTML = data.chapters.map((c, i) => {
      const w = Math.round(width * (c.end - c.start) / data.total);
      return `<div class="seg" data-seg="${i}" style="width:${w}px"><p class="seg-label">${esc(c.name)}</p>` +
        `<div class="seg-track"><div class="seg-fill"></div></div></div>`;
    }).join("");
    return true;
  }

  function slotAt(t) {
    let k = 0;
    while (k < D.slots.length - 1 && t >= D.slots[k + 1].start) k++;
    return k;
  }

  function headline(slot, t) {
    let ci = 0;
    slot.chunks.forEach((c, i) => { if (c.length && t >= c[0].t) ci = i; });
    if (drawn.slot !== slot.id || drawn.chunk !== ci) {
      $("hl-cur").innerHTML = wordsHtml(slot.chunks[ci] || []);
      $("hl-prev").innerHTML = ci > 0 ? wordsHtml(slot.chunks[ci - 1]) : "";
      drawn = {slot: slot.id, chunk: ci};
    }
    const cur = slot.chunks[ci] || [];
    let shown = 0;
    $("hl-cur").querySelectorAll(".w").forEach((el, i) => {
      const p = clamp((t - cur[i].t) / WORD);
      if (p > 0) shown++;
      fade(el, p, 14);
    });
    const prev = $("hl-prev");
    if (ci > 0) {
      const p = clamp((t - cur[0].t) / OUT);
      if (p < 1) anim = true;
      prev.style.opacity = String(1 - ease(p));
      prev.style.transform = `translateY(${-60 * ease(p)}px)`;
      $("hl-cur").style.transform = `translateY(${(1 - ease(p)) * 60}px)`;
    } else {
      prev.style.opacity = "0";
      $("hl-cur").style.transform = "";
    }
    return `${ci}.${shown}`;
  }

  function progress(t) {
    let key = "";
    document.querySelectorAll(".seg").forEach((seg, i) => {
      const c = D.chapters[i];
      const w = parseFloat(seg.style.width);
      const px = Math.floor(clamp((t - c.start) / (c.end - c.start)) * w / 4) * 4;  // 4 px steps
      seg.querySelector(".seg-fill").style.width = px + "px";
      seg.classList.toggle("on", t >= c.start && t < c.end);
      key += px + ",";
    });
    return key;
  }

  function seek(t) {
    anim = false;
    const k = slotAt(t);
    const slot = D.slots[k];
    const prev = D.slots[k - 1];
    const local = t - slot.start;
    $("kicker").textContent = slot.kicker;
    document.body.classList.toggle("big", slot.kind === "card");
    const hk = headline(slot, t);
    // the browser frame: in for app/paypal scenes (no fade between two recorded scenes)
    const recorded = slot.kind === "app" || slot.kind === "paypal";
    const prevRec = prev && (prev.kind === "app" || prev.kind === "paypal");
    fade($("frame"), recorded ? (prevRec ? 1 : clamp(local / IN)) : 0, 30);
    let url = "";
    if (recorded) {
      (slot.urls || []).forEach((u) => { if (t >= u.t) url = u.url; });
      $("url").textContent = url.replace(/^https?:\/\//, "");
      $("lock").textContent = url.startsWith("https://") ? "🔒" : "ⓘ";
      $("hole-label").textContent = D.preview ? `app recording · ${slot.id}` : "";
    }
    // slides and cards
    document.querySelectorAll(".slide").forEach((el) => {
      const on = !recorded && el.id === "slide-" + slot.slide;
      el.style.display = on ? SHOW[slot.slide] : "none";
      if (on) fade(el, clamp(local / IN), 20);
    });
    let cues = 0;
    document.querySelectorAll(".cue").forEach((el) => { el.style.opacity = "0"; });
    (slot.cues || []).forEach((c) => {
      const el = $(c.id);
      if (!el) return;
      const p = clamp((t - c.t) / IN);
      if (p > 0) cues++;
      fade(el, p, el.classList.contains("x") ? 0 : 18);
      if (el.classList.contains("x")) el.style.transform = `scale(${1.8 - 0.8 * ease(p)})`;
    });
    const pk = progress(t);
    return anim ? `anim@${t.toFixed(3)}` : `${slot.id}|${hk}|${cues}|${url}|${pk}`;
  }

  window.SG = {init, seek};
})();

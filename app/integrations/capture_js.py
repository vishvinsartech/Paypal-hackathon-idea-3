"""In-page script for the live Playwright capture: text blocks + computed style + hidden state + checkboxes."""

CAPTURE_JS = r"""
() => {
  const BLOCK = new Set(["P","H1","H2","H3","H4","LI","DIV","SUMMARY","LABEL","A","BUTTON","SPAN","HEADER",
                         "SECTION","ARTICLE","TD","TH","MAIN","BODY"]);
  const hiddenReason = (el) => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === "none") return "display:none";
      if (cs.visibility === "hidden") return "visibility:hidden";
      const d = n.parentElement;
      if (d && d.tagName === "DETAILS" && !d.open && n.tagName !== "SUMMARY") return "collapsed";
    }
    return null;
  };
  const ignored = (el) => !!el.closest("[data-subguard-ignore]");
  const out = {blocks: [], checkboxes: [], links: []};
  for (const el of document.body.querySelectorAll("*")) {
    if (!BLOCK.has(el.tagName) || ignored(el)) continue;
    let text = "";
    const walk = (node) => {
      for (const c of node.childNodes) {
        if (c.nodeType === 3) text += c.textContent + " ";
        else if (c.nodeType === 1 && !BLOCK.has(c.tagName) && !["SCRIPT","STYLE"].includes(c.tagName)) walk(c);
      }
    };
    walk(el);
    text = text.replace(/\s+/g, " ").trim();
    if (!text) continue;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const tid = el.closest("[data-testid]");
    out.blocks.push({text, testid: tid ? tid.dataset.testid : null, hidden_reason: hiddenReason(el),
      font_px: parseFloat(cs.fontSize), color: cs.color,
      bbox: [r.x + scrollX, r.y + scrollY, r.width, r.height]});
  }
  for (const cb of document.querySelectorAll("input[type=checkbox]")) {
    if (ignored(cb)) continue;
    out.checkboxes.push({name: cb.name || "", value: cb.value || "", testid: cb.dataset.testid || null,
                         checked: cb.defaultChecked});
  }
  for (const a of document.querySelectorAll("a[href]")) {
    out.links.push({href: a.getAttribute("href"), text: a.textContent.trim()});
  }
  return out;
}
"""

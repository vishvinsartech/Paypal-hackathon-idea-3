// Chat drawer: streams /api/chat (SSE over fetch), shows tool chips and confirmation cards (spec 7.3).
(function () {
  "use strict";
  const panel = document.getElementById("chat");
  if (!panel || !window.SG) return;
  const {user, esc, showCard, resultLines, refresh} = window.SG;
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const openBtn = document.getElementById("chat-open");
  const history = [];
  let busy = false;

  function setOpen(open) {
    panel.hidden = !open;
    openBtn.setAttribute("aria-expanded", String(open));
    if (open) input.focus(); else openBtn.focus();
  }
  openBtn.addEventListener("click", () => setOpen(panel.hidden));
  document.getElementById("chat-close").addEventListener("click", () => setOpen(false));
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });

  function bubble(role, text, testid) {
    const el = document.createElement("div");
    el.className = "msg msg-" + role;
    if (testid) el.dataset.testid = testid;
    el.textContent = text || "";
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function chip(text, ok) {
    const el = document.createElement("span");
    el.className = "chip " + (ok ? "chip-teal" : "chip-red");
    el.dataset.testid = "tool-chip";
    el.textContent = text + (ok ? " ✓" : " ✗");
    let row = log.lastElementChild;
    if (!row || !row.classList.contains("chips")) {
      row = document.createElement("div");
      row.className = "chips";
      log.appendChild(row);
    }
    row.appendChild(el);
  }

  async function handleCard(card) {
    const host = document.createElement("div");
    host.className = "msg msg-card";
    log.appendChild(host);
    log.scrollTop = log.scrollHeight;
    const out = await showCard(card, host);
    if (!out) { bubble("agent", "Okay, nothing was cancelled."); return; }
    host.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    if (out.results) out.results.forEach((r) => chip(`PayPal ${transportName(r.transport)} · cancel`, r.ok));
    const lines = resultLines(out).map((l) => l.text);
    const allOk = out.all_ok && !out.error;
    const done = bubble("agent", (allOk ? "Done. " : "Not everything worked. ") + lines.join(" "), "chat-done");
    done.classList.toggle("msg-warn", !allOk);
    history.push({role: "assistant", content: done.textContent});
    await refresh();
  }

  function transportName(t) {
    return {mcp: "MCP", sdk: "SDK", rest: "REST", mock: "mock"}[t] || (t || "");
  }

  async function send(text) {
    if (busy || !text.trim()) return;
    busy = true;
    document.getElementById("chat-suggest").hidden = true;
    bubble("user", text);
    input.value = "";
    const reply = bubble("agent", "…");
    let replyText = "";
    const cards = [];
    try {
      const res = await fetch("/api/chat", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({user_id: user, message: text, history})});
      if (!res.ok || !res.body) throw new Error("The chat isn't available right now.");
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {stream: true});
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 2);
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "text" || ev.type === "error") {
            replyText += (replyText ? " " : "") + ev.text;
            reply.textContent = replyText;
            if (ev.type === "error") reply.classList.add("msg-warn");
          } else if (ev.type === "tool") {
            chip(ev.label, ev.ok);
            log.appendChild(reply); // keep the answer below the chips
          } else if (ev.type === "card") {
            cards.push(ev.card);
          }
        }
      }
    } catch (err) {
      replyText = err.message;
      reply.classList.add("msg-warn");
    }
    reply.textContent = replyText || "(no answer)";
    history.push({role: "user", content: text}, {role: "assistant", content: replyText});
    busy = false;
    for (const card of cards) await handleCard(card);
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  document.getElementById("chat-suggest").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) send(b.textContent);
  });
})();

// Cancellation email preview (D-104, demo only): editable To / Subject / Body, then Send (demo outbox),
// Open in Gmail (compose link with the CURRENT edited text) or Close (the draft is kept). Nothing is sent
// without a click; a second Send shows the email already sent. Exposes SG.openEmail(noticeId, {justCancelled}).
(function () {
  "use strict";
  if (!window.SG) return;
  const {user, esc, api, toast, refresh} = window.SG;
  const GMAIL_MAX = 1800;
  const GMAIL = "https://mail.google.com/mail/?view=cm&fs=1";
  const KEY = (id) => "sg-email-edit-" + id;
  const dlg = document.createElement("dialog");
  dlg.className = "dialog email-dialog";
  dlg.dataset.testid = "email-preview";
  dlg.setAttribute("aria-labelledby", "email-title");
  document.body.appendChild(dlg);
  let done = null; // resolves openEmail's promise when the dialog closes

  const gmailUrl = (to, su, body) => `${GMAIL}&to=${encodeURIComponent(to)}&su=${encodeURIComponent(su)}&body=${encodeURIComponent(body)}`;
  function saveEdit(id, v) { try { localStorage.setItem(KEY(id), JSON.stringify(v)); } catch (e) { /* storage off */ } }
  function loadEdit(id) { try { return JSON.parse(localStorage.getItem(KEY(id)) || "null"); } catch (e) { return null; } }
  function dropEdit(id) { try { localStorage.removeItem(KEY(id)); } catch (e) { /* storage off */ } }

  function sentView(n, justCancelled) {
    const label = n.sent_via === "gmail_compose_link" ? "Opened in Gmail (demo)" : "Email sent (demo)";
    dlg.innerHTML = `<form method="dialog" class="email-card">
      ${justCancelled ? `<p class="email-ok" data-testid="email-paypal-done">Cancelled in PayPal. You won't be charged.</p>` : ""}
      <h3 id="email-title" data-testid="email-sent">${label}</h3>
      <p class="muted small">To ${esc(n.to)} · Day ${n.sim_day} · edited: ${n.edited ? "yes" : "no"} · demo only, no real email was sent by SubGuard</p>
      <p><strong>${esc(n.subject)}</strong></p><pre class="email-pre">${esc(n.body)}</pre>
      <p class="tiny muted">SHA-256: <code>${esc(n.sha256)}</code></p>
      <div class="row"><button class="btn btn-ghost" value="close" data-testid="email-dismiss">Close</button></div></form>`;
  }

  function editView(n, justCancelled) {
    const v = loadEdit(n.id) || {to: n.to, subject: n.subject, body: n.body};
    dlg.innerHTML = `<form method="dialog" class="email-card">
      ${justCancelled ? `<p class="email-ok" data-testid="email-paypal-done">Cancelled in PayPal. You won't be charged.</p>` : ""}
      <h3 id="email-title">Your cancellation email to ${esc(n.to)}</h3>
      <p class="muted small">Penwright's terms ask for written notice by email. Check it, edit it, then send. Drafted by <span data-testid="email-drafted-by">${esc(n.drafted_by)}</span>.</p>
      <label class="field">To<input type="email" data-testid="email-to" value="${esc(v.to)}" required></label>
      <label class="field">Subject<input data-testid="email-subject" value="${esc(v.subject)}"></label>
      <label class="field">Body<textarea rows="12" data-testid="email-body">${esc(v.body)}</textarea></label>
      <p class="warn small" data-testid="email-too-long" hidden>Too long for Gmail link; copy the text instead
        <button type="button" class="btn btn-sm btn-ghost" data-testid="email-copy">Copy</button></p>
      <p class="muted tiny">Demo only: Send saves it to the demo outbox. Production would send from your own Gmail/Outlook with send-only permission.</p>
      <div class="row">
        <button type="button" class="btn" data-testid="email-send">Send</button>
        <button type="button" class="btn btn-ghost" data-testid="email-open-gmail">Open in Gmail</button>
        <button class="btn btn-ghost" value="close" data-testid="email-dismiss">Close</button>
      </div></form>`;
    const $ = (id) => dlg.querySelector(`[data-testid=${id}]`);
    const read = () => ({to: $("email-to").value.trim(), subject: $("email-subject").value, body: $("email-body").value});
    const sync = () => {
      const cur = read();
      $("email-send").disabled = !cur.to || !cur.body.trim();
      $("email-open-gmail").disabled = $("email-send").disabled;
      saveEdit(n.id, cur);
    };
    dlg.querySelectorAll("input, textarea").forEach((el) => el.addEventListener("input", sync));
    sync();
    async function finish(kind) {
      const res = await api(`/api/notices/${n.id}/${kind}`, {method: "POST", body: Object.assign({user_id: user}, read())});
      if (res.too_long) { $("email-too-long").hidden = false; return; }
      dropEdit(n.id);
      sentView(res.notice, justCancelled);
      refresh();
    }
    $("email-send").addEventListener("click", () => {
      $("email-send").disabled = true;
      finish("send").catch((e) => { toast(e.message, {level: "urgent"}); sync(); });
    });
    $("email-open-gmail").addEventListener("click", () => {
      const cur = read();
      const url = gmailUrl(cur.to, cur.subject, cur.body);
      if (url.length > GMAIL_MAX) { $("email-too-long").hidden = false; return; }
      window.open(url, "_blank", "noopener"); // opened in the click itself, so it isn't popup-blocked
      finish("gmail").catch((e) => toast(e.message, {level: "urgent"}));
    });
    $("email-copy").addEventListener("click", async () => {
      const cur = read();
      try {
        await navigator.clipboard.writeText(`To: ${cur.to}\nSubject: ${cur.subject}\n\n${cur.body}`);
        toast("Copied. Paste it into your email app.");
      } catch (e) {
        $("email-body").select();
        toast("Select-all is on: press Ctrl+C to copy.");
      }
    });
  }

  dlg.addEventListener("close", () => { if (done) { const d = done; done = null; d(); } });

  // Opens the preview for a notice; resolves when it's closed.
  async function openEmail(noticeId, opts) {
    const n = (await api(`/api/notices?user=${user}`)).find((x) => x.id === noticeId);
    if (!n) { toast("That email isn't available.", {level: "urgent"}); return; }
    const just = !!(opts && opts.justCancelled);
    if (n.status === "sent") sentView(n, just); else editView(n, just);
    if (dlg.open) dlg.close();
    dlg.showModal();
    return new Promise((resolve) => { done = resolve; });
  }

  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-email-open]");
    if (b) { ev.preventDefault(); openEmail(b.dataset.emailOpen); }
  });
  window.SG.openEmail = openEmail;
})();

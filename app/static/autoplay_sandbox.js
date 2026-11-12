// "Start demo" in sandbox mode (D-116/D-117), steps 1-2 of the stepper. Penwright opens in its own window and
// plays Priya: the SubGuard companion reviews the page (real LLM), "Continue to PayPal" and "Subscribe with PayPal".
// The presenter only confirms the order in PayPal's window, which opens already logged in as the sandbox buyer
// (D-168).
// The window reports each stage here with postMessage, shows the live PayPal card, and closes itself.
// Hosted (D-192): the window says `manual`; the presenter logs in to PayPal there and approves. If a message is
// lost (or the window closes first), the poll below still finds the new subscription.
(function () {
  "use strict";
  window.SGSandboxStart = function (win, ui) {
    const {mark, say, esc, user} = ui;
    return new Promise((resolve, reject) => {
      let review = null;
      let finished = false;
      let manual = false;
      let ticks = 0;
      const finish = () => {
        finished = true;
        clearInterval(watch);
        window.removeEventListener("message", onMessage);
      };
      const subscribed = (sub) => {
        finish();
        mark("approve", "done", `PayPal ${sub.status}`);
        say(`Subscribed in the PayPal sandbox: <code>${esc(sub.paypal_id)}</code> is ${esc(sub.status)}. ` +
          "The Penwright window closes by itself.");
        resolve({pre: review, sub});
      };
      // The dashboard's own check: a Penwright subscription registered by the server (not by the window).
      const findSub = async () => {
        try {
          const res = await fetch(`/api/subscriptions?user=${encodeURIComponent(user)}`);
          if (!res.ok) return null;
          return (await res.json()).find((s) => s.merchant_id === "penwright" && s.status === "ACTIVE") || null;
        } catch (e) { return null; }
      };
      function onMessage(ev) {
        if (ev.origin !== location.origin || ev.source !== win || !ev.data || ev.data.type !== "subguard-demo") return;
        const d = ev.data;
        if (d.stage === "reading") {
          say("<strong>Day 0.</strong> Priya clicks PayPal on Penwright. SubGuard reads the fine print first…");
        } else if (d.stage === "review") {
          review = d.review;
          mark("read", "done", `Risk ${review.risk_score}` + (review.display ? ` · act by ${review.display.points.act_by.date}` : ""));
          say(esc(review.summary || ""));
        } else if (d.stage === "ready" && d.manual) {
          manual = true;
          mark("approve", "active", "your turn");
          say("<strong>Your turn.</strong> In the Penwright window, click <strong>Subscribe with PayPal</strong> and " +
            "log in with the sandbox buyer shown there. The demo continues here once PayPal says yes.");
        } else if (d.stage === "ready") {
          mark("approve", "active", "Subscribe…");
          say("Priya clicks <strong>Subscribe with PayPal</strong>. PayPal's window opens next.");
        } else if (d.stage === "approving" && manual) {
          mark("approve", "active", "approve in PayPal");
          say("<strong>Your turn: approve in PayPal.</strong> Log in with the sandbox buyer and approve the " +
            "subscription; the demo continues here once PayPal says yes.");
        } else if (d.stage === "approving") {
          mark("approve", "active", "confirm the order");
          say("<strong>Your turn: confirm the order.</strong> PayPal's window is open, logged in as Priya's sandbox " +
            "account. Confirm the subscription there; the demo continues here once PayPal says yes.");
        } else if (d.stage === "retry") {
          mark("approve", "active", "not confirmed");
          say(esc(d.message) + " Click <strong>Subscribe with PayPal</strong> in the Penwright window to try again.");
        } else if (d.stage === "subscribed") {
          subscribed(d.sub);
        } else if (d.stage === "error") {
          finish();
          reject(new Error(d.message || "The Penwright window reported an error"));
        }
      }
      const watch = setInterval(async () => {
        if (finished) return;
        ticks += 1;
        const closed = win.closed;
        if (!closed && ticks % 4) return;  // poll every 4 s while the window is open, at once when it closes
        const sub = await findSub();
        if (finished) return;
        if (sub) return subscribed(sub);
        if (closed) {
          finish();
          reject(new Error("The Penwright window was closed before the trial was set up."));
        }
      }, 1000);
      window.addEventListener("message", onMessage);
      mark("read", "active", "opening Penwright…");
      say("<strong>Day 0.</strong> Priya opens Penwright in a new window…");
      win.location.href = `/shop/penwright?user=${encodeURIComponent(user)}&autodemo=1`;
    });
  };
})();

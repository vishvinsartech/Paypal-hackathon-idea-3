// "Start demo" in sandbox mode (D-116/D-117), steps 1-2 of the stepper. Penwright opens in its own window and
// plays Priya: the SubGuard companion reviews the page (real LLM) and "Continue to PayPal". The presenter clicks
// "Subscribe with PayPal" and confirms in PayPal's window, which opens already logged in as the sandbox buyer.
// The window reports each stage here with postMessage, shows the live PayPal card, and closes itself.
(function () {
  "use strict";
  window.SGSandboxStart = function (win, ui) {
    const {mark, say, esc, user} = ui;
    return new Promise((resolve, reject) => {
      let review = null;
      let finished = false;
      const finish = () => {
        finished = true;
        clearInterval(watch);
        window.removeEventListener("message", onMessage);
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
        } else if (d.stage === "ready") {
          mark("approve", "active", "click Subscribe");
          say("In the Penwright window, click <strong>Subscribe with PayPal</strong>.");
        } else if (d.stage === "approving") {
          mark("approve", "active", "confirm in PayPal");
          say("PayPal's window is open, logged in as Priya's sandbox account. <strong>Confirm the subscription " +
            "there</strong>; the demo continues here once PayPal says yes.");
        } else if (d.stage === "retry") {
          mark("approve", "active", "not confirmed");
          say(esc(d.message) + " Click <strong>Subscribe with PayPal</strong> in the Penwright window to try again.");
        } else if (d.stage === "subscribed") {
          finish();
          mark("approve", "done", `PayPal ${d.sub.status}`);
          say(`Subscribed in the PayPal sandbox: <code>${esc(d.sub.paypal_id)}</code> is ${esc(d.sub.status)}. ` +
            "The Penwright window closes by itself.");
          resolve({pre: review, sub: d.sub});
        } else if (d.stage === "error") {
          finish();
          reject(new Error(d.message || "The Penwright window reported an error"));
        }
      }
      const watch = setInterval(() => {
        if (win.closed && !finished) {
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

# SubGuard v3: fix plan for Claude Code

> Save this file in the repo as `docs/FIX_PLAN.md`. Every phase below is self-contained, so you can run one phase per session.

You are working in the SubGuard repo (FastAPI + Jinja + vanilla JS, JSON storage, PayPal sandbox, Anthropic/OpenAI). Branch `prototype-v2` is the starting point. **Create branch `prototype-v3` from it and work there.**

**Hackathon deadline: 12 Nov 2026, 12:00 PST (13 Nov 01:30 IST).** Work in phase order. Each phase must leave the app working, with `make test`, `make lint` and `make ui-check` passing. Commit at the end of every phase, with a message that starts `vN: Phase X`.

## How to work

- Read `CLAUDE.md`, `README.md`, `docs/DECISIONS.md` and this file before you start.
- Every item has an ID (B1, D6, U12…). When you finish an item, tick it in the **Coverage checklist** at the bottom of this file, with the commit hash.
- Record every new decision in `docs/DECISIONS.md` as `D-130` onwards.
- Don't ask me questions unless something needs a credential or can't be undone. Pick the simplest option that meets the acceptance check, write it down, and continue.
- **Keep as they are:** the safety rules R1–R7 (`policy.py`), the hash-chained audit log, JSON storage, the single worker, no React, no new frameworks. AG Grid and AG Charts stay, but load them from a vendored copy (see U30).
- After any UI change, take screenshots at **1440×900** and **390×844** with Playwright into `docs/img/v3/`, and look at them yourself before you tick the item.
- If time runs short, stop after Phase 4. Phases 5–6 are polish.

---

## Phase 0: Baseline (15 min)

1. Create branch `prototype-v3`. Run `make test` (expect 286 passed), `make lint` and `make ui-check`. Write down the numbers.
2. Add `scripts/shots.py`. It starts a mock server on throwaway data, walks the demo, and saves screenshots of every screen at both viewports (shop, companion, dashboard Days 0/5/11, cancel confirmation, email modal, every dashboard section, subscription page). Re-run it after each phase.

---

## Phase 1: Correctness bugs and story logic

### Bugs found while running the app

- **B1. The companion opens scrolled to the bottom.** At 1440×900 the risk badge is 426 px above the visible area, because the initial focus on "Back out" scrolls the `.sg-card`.
  *Fix:* put the initial focus on the dialog title (`tabindex=-1`, `focus({preventScroll:true})`), set `scrollTop=0` when it opens, and keep the header and footer buttons sticky.
  *Check:* a Playwright test asserts `companion-risk` is inside the viewport when the overlay opens, at 1440×900 and 390×844.
- **B2. Wrong deadlines after the clock has moved.** Opening the shop on Day 11 shows "real cancel deadline is Day 18 … first charge Day 22", while the cross-check table in the same modal says "First charge day 11 ✓ day 11". The cause: the review uses the current sim day as the sign-up day, but the page text and the cross-check are relative.
  *Fix:* everything a user sees in the companion is relative to sign-up or a calendar date ("Nov 18", "7 days after you start"). Absolute sim days stay internal.
  *Check:* a test opens the companion at sim day 0 and at sim day 11, and the text is the same apart from the calendar dates.
- **B3. "What SubGuard did" is empty after a manual run.** It says "Nothing yet. Press Start demo." after a manual sign-up, and it's empty on mobile even on Day 11.
  *Fix:* build the summary from the current user's subscriptions, not from the Start-demo run marker.
- **B4. The step tracker never advances when you click through by hand.**
  *Fix:* derive each step's state from the subscription's events (reviewed, approved, timer set, check-in sent, decision, Day 11 proof).
- **B5. Toasts cover content.** The Day 5 and Day 11 toasts land bottom-left over the Alerts card and its Keep/Cancel buttons.
  *Fix:* stack toasts top right under the top bar, auto-dismiss after 6 s, and keep the `aria-live` region.
- **B6. The floating "Ask SubGuard" button covers content:** "Show full log", the timeline label, the footer's "Developer" link, and the mobile subscriptions heading.
  *Fix:* move the chat entry into the top bar (icon + label). The chat stays a side drawer.
- **B7. The timeline is broken.** The axis ends at "Day 21" on Day 0 and "Day 31" on Day 11, the step-up label reads "$49.99 from Day 101", and the markers are 8 px and overlap.
  *Fix:* fixed Day 0–14 trial view with five labelled dots (see U9). Show the step-up as text: "$49.99/month from month 4".
- **B8. The Day 11 proof is credited to PayPal.** The audit row says actor `PayPal`: "First charge due: blocked", but PayPal did nothing (it's the sim clock).
  *Fix:* actor `SubGuard`, text "Checked PayPal: no active subscription, so no charge can be taken". Do a fresh live GET (sandbox) or mock GET and store its debug id as the proof.
- **B9. Mobile navigation hides sections.** The sidebar becomes a strip showing only 3 of the 5 sections.
  *Fix:* comes with U-phase restructure. Use a bottom tab bar on ≤ 640 px.
- **B10. The fallback flags "honest terms" on the trap page.** The no-AI fallback emits `CLEAR_TERMS` next to eight dark-pattern findings.
  *Fix:* never emit `CLEAR_TERMS` when any risky type is present (both paths). Add a test.
- **B11. Mock chat refuses free questions** with "switch to sandbox mode".
  *Fix:* show 3 suggested-question chips in the chat ("Should I keep it?", "What happens if I do nothing?", "Draft my cancellation email"), wired to the scripted answers in mock mode. Keep the polite message for anything else, but name the chips in it.
- **B12. Stale README facts:** "~190 tests" (there are 286+), "Hosted URL: not deployed yet", `render.yaml` deploys `main`. *Fix in Phase 4.*

### Story logic

- **D6. The deadline is one day early, and stated as fact.** The terms say notice "at least 3 days before the next billing date", and billing is Day 11, so the last valid day **by the terms is Day 8**. SubGuard aims for Day 7 as a safety margin.
  *Fix:* keep `real_cancel_deadline_day` (7) as "act by". Add `terms_last_day` (= first charge − notice = 8). Wherever the deadline appears, say "Act by Nov 18 (the terms allow Nov 19)". Use the same wording in alerts, chat answers, the email draft and the video narration.
  *Check:* a test asserts both values and the wording.
- **D7. No answer means no written notice.** After the Day 6 auto-cancel the email draft just waits.
  *Fix:*
    1. Add a checkbox to the companion, unticked by default: "If I don't answer, send the cancellation email for me." Store it on the consent snapshot.
    2. If it's ticked, the Day 6 auto-cancel also finalises the email. In the demo that means the outbox; log it under the R2 rule as `notice_auto_sent`.
    3. If it isn't ticked, send a **Day 7 reminder** ("Your cancellation email isn't sent yet. The terms need it by Nov 19.") with **Review email**.
  *Check:* story tests cover both paths.
- **D10. The savings figure is inflated.** Lead with what actually didn't happen: "$24.99 charge never taken", with "up to $524.88 in year one" as secondary. Rename the KPI to **"Charges avoided"**: the primary value is the first charge, the subtitle is the year-one figure. Update tests that assert $524.88 so they assert both.
- **Persona.** Rename **userA → Priya**, a freelance writer who pays for apps with PayPal. This covers the user id/display name, seed data, templates, alerts, the email draft ("Name: Priya Sharma"), fixtures, tests, README, scenes and narration. Keep the URL `/user` working, and add `/me` as an alias.
- **Fair Trial badge (story contradiction).** Penwright is a trap merchant, so it must **not** show "Protected by SubGuard: cancel anytime". Remove the badge from Penwright's page. Penwright stays `fair_trial_member: true` in the seed, because the demo relies on the partner path. Explain it in the README and on the evidence page: *"Penwright is connected to SubGuard through PayPal partner permissions. That lets SubGuard cancel through PayPal, but it doesn't make Penwright's terms fair."*
- **Usage evidence (D8).** Label usage honestly: "Opened twice (from Penwright's app activity, simulated in this demo)". The advice wording stays "SubGuard suggests: cancel. You decide."

---

## Phase 2: Make the AI matter (judges will ask "turn the AI off: what changes?")

Today the no-AI fallback gives the **same** risk 87, Day 7 and the same core findings as the AI on Penwright. We need a case where only the AI succeeds, shown honestly.

- **A1. Second fictional merchant "Quillnote"** (an AI notes app), `fair_trial_member: false`, so it uses the Layer 2 path. Its traps are written in plain prose that the regex rules don't catch. Write the copy yourself, but include:
  - a notice period written in words, with no "N days" pattern (for example "we'll need to hear from you in writing no later than seventy-two hours before your renewal")
  - an auto-renew clause phrased indirectly
  - a price step-up mentioned only in a FAQ answer
  - a cancellation route that's "contact our account team"
  - **no** hidden injection line (Penwright already covers that)

  Same structure as Penwright: a checkout page, a terms page, a fictional banner, and a seeded plan in mock and in sandbox (`make seed`).
- **A2. Side-by-side proof on the evidence page.** Add an "AI vs basic check" panel listing which findings each path found. Store the basic-check result with every review (run `fallback_extract` alongside, which is cheap). For Quillnote the AI must find at least 3 risky types that the basic check misses, including the notice period, and must compute the deadline from the AI-extracted notice (72 h → 3 days).
  *Check:* `tests/test_ai_value.py` with a recorded fixture for Quillnote.
- **A3. Parse notice periods written in words.** `_notice_days` currently only reads digits from the quote. Accept the AI's `notice_days` when the verified quote states the period in words or hours ("seventy-two hours" → 3 days). The quote still has to pass the verbatim check.
- **A4. Score calibration (D3).** Small grey text currently earns points three times (`small_font` + `low_contrast` + `HIDDEN_TEXT_STYLE`).
  *Fix:*
  - Count "hard-to-read terms" once (max 10).
  - Lower `AUTO_RENEW` to 4: every subscription renews.
  - Keep injection at 0.
  - Add `tests/fixtures/honest_terms.html`, a clear monthly plan with a cancel button.

  *Check (assert in tests):* Penwright 80–92, Quillnote 70–90, honest page ≤ 25. Update `README` and the risk formula docs to match.
- **A5. Layer 2 beat.** For Quillnote, Cancel gives: the email draft + an **ACTION NEEDED** card with a one-tap link to PayPal's Automatic payments page (`PAYPAL_AUTOPAY_URL`) + polling until PayPal shows CANCELLED. This code already exists behind `toggle-fair-trial`. Surface it in the UI and in `ui-check`.
- **A6. Mock labels.** Never show "mock", "fixtures" or "AI: mock" on user-facing surfaces. Show a single small badge in the top bar instead: "Demo data" (mock) or "PayPal Sandbox · <model>" (sandbox). The audit log and `/healthz` keep the full detail.

---

## Phase 3: UI restructure (one product view, presenter overlay)

**Goal:** two surfaces instead of four:
1. the merchant checkout (someone else's site)
2. Priya's SubGuard (the product)

Demo controls become an overlay. Colours and fonts mostly stay (dark navy, teal accent, light/dark toggle). Calendar dates in this file (Nov 11/16/18/19/21/22) are examples for a sign-up on 11 Nov; compute the real ones from the sign-up time. The target layout:

```
┌ SubGuard   [PayPal Sandbox · Claude]                         Ask SubGuard  ☀/☾  Priya ┐
├───────────────────────────────────────────────┬──────────────────────────────┤
│ Penwright Studio · free trial   ACTIVE  Risk 87│ Charges avoided              │
│ $0 today, then $24.99/month from Nov 22        │ $24.99 · up to $524.88/yr    │
│ Act by Nov 18 (the terms allow Nov 19)  ← red   ├──────────────────────────────┤
│ ●──────●──────◉──────●──────●                  │ Next decision                │
│ Signed up Check-in Act by Trial ends 1st charge│ Nov 16 · keep or cancel      │
│ Nov 11   Nov 16   Nov 18  Nov 21     Nov 22     ├──────────────────────────────┤
│ [Keep] [Cancel trial] [See evidence]           │ What SubGuard did (5 rows)   │
│ Verified with PayPal ✓ I-XXXX · status read live│ Show all →                   │
├───────────────────────────────────────────────┴──────────────────────────────┤
│ ┄ Presenter (press D)  Day 0 ━━━━●━━━━ Day 11   [Open shop] [Start] [Reset] ┄ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Top bar and global (U1–U4)

- **U1.** Top bar: logo, one status badge (A6), "Ask SubGuard" (B6), a sun/moon theme icon with a tooltip (it replaces the "Dark" text toggle), and Priya's avatar. Remove the "Live demo" / "userA's dashboard" / "Shop" tabs. The shop link moves into the presenter bar.
- **U2.** Toasts as in B5.
- **U3.** Footer: Fictional merchant · PayPal Sandbox · MIT · GitHub · Developer (health, API docs).
- **U4.** Remove every developer string from user surfaces:
  - "Delivered: in_app: shown · email: mocked · sms: mocked" → small icons "App · Email · SMS ✓"
  - "via mock", "debug id", "PayPal-Request-Id" → move to the evidence page's PayPal tab
  - "Cancelled from an alert"
  - "drafted by mock · fixtures"
  - raw enums such as `NOTICE_PERIOD` → plain labels

### Product view at `/` (U5–U12)

- **U5.** `/` becomes Priya's dashboard (this replaces both the old live demo page and `/user`). `/?demo=1` (or the D key) shows the presenter bar. Keep the old `data-testid`s where possible. Where one has to change, update the selector contract, `scenes.json`, `ui_check.py` and the tests in the same commit.
- **U6.** Presenter bar: slim, fixed at the bottom, dashed border, hidden by default. It holds a Day scrubber (0–11, with buttons at 0/5/6/7/11), Open shop, Start demo, Reset, "Show audit log", and the Fair Trial toggle for Quillnote. The 7-step tracker becomes a compact step indicator inside this bar (B4).
- **U7.** Subscription card, one per subscription. It merges the old card and the PayPal card into one:
  - header: merchant · plan, status pill, risk badge
  - a large cost line
  - the act-by line in red
  - a 5-dot timeline with calendar dates (B7)
  - actions: Keep / Cancel trial / See evidence
  - a quiet footer: "Verified with PayPal ✓ I-xxxx · status read live" (click to expand the details)

  Remove the separate "Verified with PayPal" card and the folded "Key dates" box. The dots replace them.
- **U8.** Check-in state (Day 5): the card's top gets a yellow "Keep it or cancel?" band with usage and advice, and the card's own Keep/Cancel buttons become that decision. **Only one pair of Keep/Cancel buttons on the screen.**
- **U9.** Right column: "Charges avoided" (D10), "Next decision", and "What SubGuard did" (the 5 latest meaningful events, then "Show all" → audit drawer). Delete the lone half-width "Money protected" card.
- **U10.** Sections: merge to **Overview · Activity · Emails** (desktop: left rail or tabs; mobile: bottom tab bar). History (an AG Grid for one row) folds into Activity as a simple list, with the grid only under "Show all" when there are more than 5 rows. Analytics charts move into the evidence page.
- **U11.** Empty state (no subscriptions): one friendly card, "No subscriptions yet. When you start a free trial, SubGuard checks it before you pay," plus an "Open the demo shop" button. No zero KPIs.
- **U12.** Cancel confirmation: "Cancel Penwright trial? You won't be charged $24.99 on Nov 22." Buttons: Confirm cancel / Not now. Remove the repeated "$524.88/yr" and "This can't be undone". Instead, the success state offers "Start a new trial" with the note "Penwright may not offer a second free trial."
- **U13.** Email modal: keep the structure. Highlight the quoted clause inside the body. Rename "Open in Gmail" to **"Open in my email app"** (a `mailto:` link, plus Gmail as a secondary link). The demo note stays small.

### Companion overlay (U14–U18): the hero screen

- **U14.** Order: header (shield, "SubGuard checked this offer", risk badge) → **verdict**: "$0 today, then $24.99/month from Nov 22" → sub-line "Rises to $49.99 after 3 months · up to $524.88 in year one" → **3 things to know** (the top 3 findings by severity, one line each) → **PayPal check** box (warning colour): "The page says $0 today. The PayPal plan charges $24.99 on Nov 22." → the D7 checkbox → buttons Back out / Continue to PayPal.
- **U15.** "Show evidence (8 quoted clauses, cross-check table)" is folded by default. When open, it shows quotes in plain language with the type as a small chip, and drops duplicate quotes.
- **U16.** The cross-check table leads with the failing row. Rename the confusing rows ("PayPal price $24.99 | fine print or terms only" → "Price $24.99 shown only in fine print ✓").
- **U17.** At most 720 px tall on desktop, with an internally scrolling middle and sticky header and footer. On ≤ 640 px it becomes a bottom sheet.
- **U18.** The prompt-injection finding shows as a small shield note: "Hidden instructions to AI found on this page and ignored."

### Merchant shop (U19–U22)

- **U19.** Remove `/shop` index's "Show what's hidden" spoiler. `/shop` lists the two fictional merchants as product cards.
- **U20.** Make Penwright (and Quillnote) look like a believable SaaS checkout: a hero with the product name and a one-line pitch, a 3-item feature list, a plan card ("10-day free trial, $0 today" big), the 9 px grey fine print under the price, the collapsed Terms accordion, and a PayPal button styled like PayPal's (gold, logo text). Keep the merchant's own colour scheme, clearly different from SubGuard. Keep the "Fictional merchant" banner.
- **U21.** In mock mode the button text is just "PayPal". Show the note "Demo: simulated PayPal approval" as a small badge under it. In sandbox mode, use the real JS SDK button.
- **U22.** After approval the merchant page shows only "You're subscribed. Welcome to Penwright." plus "Open SubGuard ↗" (from the companion strip). Move the PayPal debug card off the merchant page.

### Evidence page `/subscriptions/{id}` (U23–U26)

- **U23.** Tabs: **Summary** (verdict, 3 things, dates, AI vs basic check from A2) · **Evidence** (a readable page preview at full width with highlighted elements, then quotes) · **PayPal check** (cross-check table, consent snapshot, live PayPal card with ids) · **Activity** (meaningful events; "Show raw log" for everything, CSV export).
- **U24.** Findings use plain labels and severity chips. No raw `llm` / `paypal_check` source strings; show "AI" / "Code check" / "PayPal".
- **U25.** Charts from the old Analytics section live in Summary. Group "Why SubGuard flagged it" into 4 categories: Hidden deadline, Price jumps, Hard to cancel, Hard-to-read terms.
- **U26.** Audit noise (D15): tag poller `paypal_call` entries `routine: true` (still hash-chained). Hide them by default in every grid and summary.

### Mobile and accessibility (U27–U30)

- **U27.** At 390 px: the top bar fits on one line, the companion is a bottom sheet, the sections use a bottom tab bar, and nothing overlaps.
- **U28.** Keyboard: the companion traps focus and closes with Esc, focus is visible everywhere, and all buttons have labels. Contrast meets WCAG AA in both themes. The merchant's grey fine print is the one intentional exception.
- **U29.** Motion: keep the subtle entrance and count-up animations, but respect `prefers-reduced-motion`. The count-up must finish before a screenshot (the video recorder waits for `data-ready`).
- **U30.** Vendor AG Grid 36.2.0 and AG Charts 14.2.0 into `app/static/vendor/` (keep the licence files), so the app works without the CDN.

---

## Phase 4: Submission docs (needed to qualify)

- **S1. README.md:** restructure to:
  1. Pitch (3 lines)
  2. Hosted demo link and video link (placeholders until filled)
  3. Quick start (mock), then sandbox
  4. **How PayPal is used**: a table of each API/SDK (Subscriptions API via `paypal-server-sdk`: products, plans, create, get, cancel, update pricing; JS SDK Subscribe button; PayPal MCP server; webhooks + signature verification; Automatic payments link), what it does, and the file
  5. **How AI is used, and which tools**: provider + model, the 3 AI jobs (fine-print review, chat agent, cancellation email), the guardrails (verbatim quotes, injection ignored, code does the money maths, AI only proposes), the AI vs basic check result, and that the project was built with Claude Code
  6. Architecture (Mermaid)
  7. What's real vs simulated
  8. **Limitations** (one sandbox business plays the merchant; the sim clock; partner mode is experimental; the companion simulates a browser extension; usage is simulated; JSON storage)
  9. Safety rules R1–R7
  10. Sponsor tools (APIMatic SDK, AG Grid/Charts, Zapier, Render)
  11. Tests (actual count)
  12. License

  Keep it scannable. Move long troubleshooting into `docs/TROUBLESHOOTING.md`.
- **S2. `docs/SUBMISSION.md`:** ready-to-paste text for the form: name, tagline ("AI reads the fine print. PayPal enforces the outcome."), a 150-word description, features, how PayPal is used, AI tools used and how, sponsor tools, what's next (Fair Trial partner program → PayPal wallet feature), links (placeholders).
- **S3. `docs/ARCHITECTURE.md`:** a Mermaid flow (Shop → Companion → Review pipeline (capture → AI → verify → code checks → PayPal cross-check → risk) → Policy → Gateway (SDK/MCP/REST) → PayPal Sandbox; Timers/Escalation → Notify (Zapier/outbox); everything → JSON store + audit log), plus the trust boundaries.
- **S4. Clean-up:** move `docs/BUILD_PROMPT.md` and the milestone 1–8 history from `docs/PROGRESS.md` into `docs/archive/`. Update `CLAUDE.md` with the new story (Priya, Penwright + Quillnote, Day 8 vs act-by Day 7).
- **S5. Render:** set `render.yaml` `branch: prototype-v3` (I will merge to `main` later). Document which secrets to set for a sandbox-mode hosted demo (`APP_MODE=sandbox`, PayPal client id/secret, LLM key, buyer email/password). Mock stays the fallback.
- **S6. Licence:** confirm `LICENSE` is the standard MIT text so GitHub detects it.

---

## Phase 5: Video tooling (code only; I record)

- **V1.** Update `demo-video/scenes.json` to these beats. The total must be ≤ 170 s, with the cap at 175 s.

| # | s | Beat |
|---|---|---|
| 01_hook | 10 | "Free trials are designed to be forgotten." Priya's empty SubGuard |
| 02_shop | 15 | Penwright checkout, fine print, Terms |
| 03_companion | 25 | Verdict, act by Nov 18 (terms allow Nov 19), PayPal check box, injection ignored, consent checkbox |
| 03b_paypal | 15 | Hand-recorded real PayPal sandbox approval clip |
| 04_ai_vs_basic | 15 | Quillnote evidence page: the AI found it, the basic check missed it |
| 05_checkin | 15 | Day 5 check-in band (and the Zapier email if configured) |
| 06_cancel | 30 | Cancel, PayPal CANCELLED read live, AI email quoting the clause, Send |
| 07_audit | 15 | Activity with R1/R2, "Show raw log" |
| 08_proof_scale | 20 | Day 11 proof, then one line on scale: Fair Trial (partner) / Layer 2 (Quillnote one-tap) / PayPal wallet |
| 09_close | 10 | Charges avoided, MIT, repo URL |

- **V2.** Write the missing `demo-video/record_demo.py`, `make_voiceover.py` and `make_video.sh`, following the existing `check_scenes.py`, `build_video.py` and `videolib.py` and the rules in `demo-video/README.md` (never extend a scene, hard cap under 180 s verified with ffprobe, `-preset veryfast`). The recorder must support `APP_MODE=sandbox` with a pre-approved subscription, so the video shows "PayPal Sandbox", not "Demo data".
- **V3.** `make demo-video-check` passes: every selector exists, and the narration fits each scene at 125 wpm. No real brands in captions. Write "Open in my email app", not "Gmail".

---

## Phase 6: Final verification

1. `make test` and `make lint` are clean. `make ui-check` drives the new story (Penwright cancel path, no-answer path with and without D7 consent, Keep path, Quillnote Layer 2 path) with no console errors.
2. If `.env` has sandbox keys: `make seed`, `make sandbox-ui-check` and `make sandbox-check` pass, and the Quillnote plan is seeded.
3. Run `scripts/shots.py` and review every screenshot against U1–U30. Fix anything overlapping, cut off or showing developer text.
4. Fill the Coverage checklist below with a commit hash for every ID. Any ID left open gets one line saying why.
5. Report back to me:
   - what changed
   - the test count
   - the screenshots folder
   - the exact commands to run the demo in mock and sandbox mode
   - which human tasks remain (list below)

## Human tasks (you can't do these; prepare everything they need)

- Make the GitHub repo public. Check that MIT shows in the About section.
- Merge `prototype-v3` → `main`, or keep the Render branch.
- Deploy on Render, set the secrets, and paste the URL into the README and SUBMISSION.
- Record the PayPal approval clip, run `make demo-video`, and upload to YouTube as public.
- (Optional) Create the Zapier Catch Hook and set `ZAPIER_CATCH_HOOK_URL`.

## Coverage checklist (tick each with a commit hash)

| ID | Done | Commit | Note |
|---|---|---|---|
| B1 companion scroll | [x] | b76a096, b4396cd | focus title, sticky head/foot, max 720 px; ui-check at both viewports (D-140) |
| B2 day offset | [x] | b76a096 | preflight `display` block, relative + calendar dates (D-131) |
| B3 empty summary | [x] | a312faf | drew only on the 5 s refresh; now on load (D-137) |
| B4 step tracker | [x] | a312faf | `app/core/steps.py`, derived from audit events (D-137) |
| B5 toasts | [x] | 514dce0 | top right, 6 s, aria-live (D-139) |
| B6 chat button | [x] | 514dce0 | in the top bar (D-139) |
| B7 timeline | [x] | 514dce0 | fixed Day 0-14, five dots; U7 moves it onto the merged card (D-138) |
| B8 Day 11 actor | [x] | 181397d | fresh GET, status + debug id stored; audit actor stays `system` (D-134) |
| B9 mobile nav | [ ] | | deferred to Phase 3 with U10/U27, as the item says |
| B10 CLEAR_TERMS | [x] | b76a096 | both paths + tests (D-136) |
| B11 chat chips | [x] | 514dce0 | 3 chips, scripted answers from tool results (D-139) |
| B12 README facts | [ ] | | Phase 4 (S1), as the item says |
| D6 Day 8 vs act-by Day 7 | [x] | b76a096 | `terms_last_day`; one wording in companion, alerts, card, chat, sub page, narration (D-132) |
| D7 consent / Day 7 reminder | [x] | 7104e36 | opt-in box -> `notice_auto_sent` (R2); else Day 7 reminder (D-133) |
| D8 usage label | [x] | b76a096 | |
| D10 charges avoided | [x] | 181397d | $24.99 + "up to $524.88 in year one"; confirm card still /yr until U12 (D-135) |
| Persona Priya | [x] | a1ff74b | id `priya`, `full_name` Priya Sharma, `/me` (D-130) |
| Fair Trial badge | [x] | 514dce0 | badge gone, member kept, partner note on evidence page + README (D-141) |
| A1 Quillnote | [ ] | | |
| A2 AI vs basic | [ ] | | |
| A3 notice in words | [ ] | | |
| A4 calibration | [ ] | | |
| A5 Layer 2 beat | [ ] | | |
| A6 mock labels | [ ] | | |
| U1–U4 global | [ ] | | |
| U5–U13 product view | [ ] | | |
| U14–U18 companion | [ ] | | |
| U19–U22 shop | [ ] | | |
| U23–U26 evidence page | [ ] | | |
| U27–U30 mobile/a11y/vendor | [ ] | | |
| S1–S6 docs | [ ] | | |
| V1–V3 video tooling | [ ] | | |
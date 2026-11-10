# SubGuard build progress

Milestones from `docs/BUILD_PROMPT.md` section 12. Tick each one only after its check passes and it is committed.

> **Story simplified after milestone 8 (2026-11-10):** userA + Penwright only (D-090). The milestone 1-8 entries
> below are a history log and still mention the old two-story demo (John, Lumen, Framewise, add-on, Day 21
> price rise, $872.76). Current numbers: Money protected **$524.88**, Penwright risk **87**. See
> "Story simplification" under the notes.

- [x] **1. Preflight.** Run `claude mcp list`; check Python >= 3.11, Node >= 18 and `npx`; install the APIMatic PayPal context plugin; write `docs/PAYPAL_TOOLS.md` and `docs/PAYPAL_SDK_NOTES.md`; create `docs/DECISIONS.md`.
  - *Check:* tool versions confirmed; the three docs exist.
  - Done 2026-11-10 (commit `3a05a3e`). Python 3.14.4, Node 24.15, npx 11.14. **Open:** the APIMatic plugin isn't installed, and the PayPal MCP isn't started (DECISIONS D-003).
- [x] **2. Scaffold + JSON store + audit log + dummy shop.**
  - *Check:* `make setup && make dev` serves `/`, `/shop` and `/shop/penwright`; the store and audit log tests pass (atomic write, corrupt-file recovery, hash chain).
  - Done 2026-11-10 (commit `a1843af`). Ran via `python scripts/tasks.py setup` / `dev` (no `make` on this machine). Every page returned 200, with no console errors in headless Chromium. 47 tests passing; ruff clean.
- [x] **3. PayPal layer (mock + SDK + MCP) + seed.**
  - *Check:* gateway tests pass in mock mode; in sandbox mode `make seed` creates the plans, and a cancel shows `CANCELLED` both via the SDK and via the PayPal MCP server.
  - Done 2026-11-10. 99 tests pass; ruff is clean. `make seed` created 3 products and 5 plans, and a re-run
    reuses them all. `sandbox-check` approved 2 Framewise subscriptions as the personal sandbox buyer,
    then cancelled one via the SDK (I-X11PUMFB87VA) and one via the PayPal MCP server (I-5NYJ1XJ1WECL).
    Both read back `CANCELLED` over both transports, and the audit chain verifies (16 entries).
- [x] **4. LLM providers + fine-print review + companion overlay.**
  - *Check:* the Penwright preflight returns >= 7 findings including `NOTICE_PERIOD`, `TERMS_MISMATCH` and `PROMPT_INJECTION_ATTEMPT`; risk 87 +/- 5; deadline day 7; every quote is verbatim. Lumen scores 15 +/- 5. The provider contract tests pass for Anthropic, OpenAI and mock.
  - Done 2026-11-10 (commit `1c207e2`). Penwright preflight: 9 findings, risk **87**, deadline Day 7 (timer 6,
    reminder 5), all quotes verbatim; Lumen **15**. Contract tests pass for all three providers (SDK fakes, D-042).
    129 tests pass; ruff clean. Companion checked in headless Chromium: overlay -> Continue -> subscribed
    (+ add-on), Escape backs out, no console errors. Live Playwright capture verified against a local server.
    **Not verified live:** real Anthropic/OpenAI calls and the sandbox JS SDK button (no browser login here).
- [x] **5. Policy, timers, escalation, clock.**
  - *Check:* Story A days 0 -> 5 -> 6 -> 15 -> 21 and Story B days 0 -> 10 -> 27 produce the right alerts, actions and audit log entries (correct actors and rule ids); `test_policy.py` covers R1-R7.
  - Done 2026-11-10 (commit `90e615e`). `tests/test_story.py` runs Story A (add-on removed on tap, timer Day 6
    shown, Day 5 reminder on in-app + email + SMS, Day 6 auto-cancel with R2 + written notice with SHA-256,
    Day 15 blocked charge, Day 21 price rise -> confirm card $228/yr -> cancelled; **$872.76** protected) and
    Story B (Lumen risk 15, no timer, 240 vs 200 yearly, 9 of 10 days used, Day 27 renewal nudge -> Keep, no
    PayPal write), checking actors and rule ids in the audit log. `tests/test_policy.py` covers R1-R7 plus
    corner cases 4, 5, 10, 11, 12, 13, 14, 29-32, 34, 36. 157 tests pass; ruff clean. Also ran Story A against
    a live mock server over HTTP (startup demo seed, outbox files, audit chain verified, no log errors).
- [x] **6. UI (AG Grid) + chat agent.**
  - *Check:* the full Story A works in mock mode in the browser with no console errors; the chat produces a confirmation card for Framewise with **$228/yr**; the audit log grid exports CSV.
  - Done 2026-11-10 (commit `9d77d13`). `python scripts/tasks.py ui-check` drove Story A through the real UI in
    headless Chromium: shop -> companion (risk 87) -> add-on removed via confirm card -> timer chip "Day 6" ->
    Day 5 toast -> Day 6 CANCELLED + notice -> Day 15 blocked charge -> Day 21 price-rise alert -> chat
    "$228/yr" card -> confirmed -> KPI **$872.76/yr** -> audit-log CSV downloaded (chain verified) ->
    subscription page. No console errors. 173 tests pass (16 new: `test_chat.py` + page tests); ruff clean.
    AG Grid Community 36.2.0 pinned (D-060). **Not verified live:** the chat with a real Anthropic/OpenAI model.
- [x] **7. Tests and hardening.**
  - *Check:* `test_scenario.py` runs Story A + B end to end in mock mode and asserts **$872.76**; every corner case in section 8 has a test or a doc note; optional `@pytest.mark.sandbox` smoke test (skipped without credentials); ruff is clean.
  - Done 2026-11-10 (commit `391215b`). `tests/test_scenario.py` runs Story A and B on one shared timeline
    (HTTP API + chat) and asserts **$872.76**, risk 87/15, deadline Day 7, injection flagged, R3 token reuse
    rejected, and every cancel paired with an allowed policy decision. `docs/CORNER_CASES.md` maps all 39
    corner cases to code + tests (3 doc notes: 1, 8, 26); a test checks that every referenced test exists.
    New code: `/webhooks/paypal` (6), currency guard (8), exports -> early-trial-end alert (27). 188 tests pass
    (`-m 'not sandbox'` by default); ruff clean; `ui-check` still passes. `pytest -m sandbox` ran against the
    real sandbox: OAuth + seeded plan prices passed; the settings check skipped (no `ANTHROPIC_API_KEY` in `.env`).
- [ ] **8. Sponsor wiring.** Zapier (real hook in sandbox + outbox in mock), `render.yaml` + deploy.
  - *Check:* Zapier delivery works (or outbox in mock); the Render URL is in the README.
  - **In progress, blocked on the user** (2026-11-10, commit `310e5d6`). Done: `render.yaml` (mock mode, Python 3.12.10,
    1 worker, `/healthz`, secrets `sync: false`); a clean copy (git files only, no `.env`) built with the exact
    build command on a fresh 3.12.10 venv and passed `/healthz` + `ui-check` Story A with the exact start command.
    Mock outbox verified by `tests/test_deploy.py`. Zapier: `scripts/zapier_check.py` + `docs/ZAPIER_SETUP.md`.
    **Missing to tick it:** (1) `ZAPIER_CATCH_HOOK_URL` in `.env`, then `python scripts/tasks.py zapier-check`
    must print `accepted`; (2) a Render deploy: the GitHub repo isn't publicly reachable and `RENDER_API_KEY` is
    empty, and the code must be pushed to the branch in `render.yaml` (`main`; work is on `prototype-v1`).
    Then put the URL in README "Hosted demo".
- [ ] **9. Demo-video tooling, code only** (section 13). Don't record or render a video.
  - *Check:* `make demo-video-check` passes.
  - Started: `demo-video/scenes.json` (10 scenes incl. the hand-recorded PayPal clip, 165 s), `check_scenes.py`,
    `build_video.py`, `videolib.py`, `demo-video/README.md` (D-114). Still to do: `record_demo.py`,
    `make_voiceover.py`, `make_video.sh`.
- [ ] **10. Docs + submission files**, then a final review against section 15.
  - *Check:* every item in section 15 "Definition of done" is satisfied.

## Notes for next session

### Start demo in sandbox mode (2026-11-11)
- Start opens Penwright in its own window, which reviews the page, approves the real sandbox subscription as the
  buyer automatically, shows the PayPal card and closes. The control room then runs the rest of the story
  (D-116). Checked against the real sandbox: review in about 18 s, ACTIVE in about 60 s, the Day 5 check-in,
  Cancel, PayPal CANCELLED, no console errors. Tests: `tests/test_demo_sandbox_start.py`.

### Key dates on userA's dashboard (2026-11-11)
- Each subscription card lists its key dates as calendar dates in the viewer's time zone: subscribed (date +
  time), check-in, auto-cancel, real last day to cancel, trial end, first charge, price rise, cancelled/kept,
  each with its sim day and state (D-115). The PayPal card shows PayPal's own start time. Tests:
  `tests/test_key_dates.py`.

### Real PayPal sandbox approval (2026-11-10)
- Sandbox checkout: companion -> real PayPal JS SDK button (server-side create) -> PayPal's approval window.
  "Subscribed via PayPal ✓" card (live status, plan, cycles, debug ids) on the shop and both dashboards; after
  Cancel the same card shows CANCELLED from PayPal + "View in PayPal sandbox" (D-113). Re-seeded the 10-day plan.
- **Verified end to end against the real sandbox** with `make sandbox-ui-check` (buyer approval in PayPal's
  window, ACTIVE -> CANCELLED read live, autopay page reached as the buyer, ids in the audit log). Run PayPal-only
  because `.env` has no LLM key: **add `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) to run sandbox mode for real.**
- Video: clip scene `03b_paypal_approval` + `check_scenes.py`, `build_video.py`, `videolib.py`,
  `demo-video/README.md` (D-114). **Still to do (milestone 9):** `record_demo.py`, `make_voiceover.py`, recording
  the clip by hand.

### Focus UI: presenter view vs userA's view (2026-11-10)
- Live demo = control room (Money protected only, alerts, timeline, audit log; Layer 2 toggle hidden). userA's
  dashboard = product (subscription card, Day 10 vs Day 7 line, Day 5 check-in with usage + advice, Day 11 proof,
  charts, AG Grid activity list, empty state). Footer + Developer menu; no Restart trial; no extra pop-ups in the
  cancel flow; shop "Show what's hidden" (D-111, D-112).
- Video: 9 scenes, 169 s, chat removed. Checks: full pytest + ruff clean; `ui_check.py` drives both pages side by
  side with no console errors.

### Analytics + userA's own view + theme (2026-11-10)
- AG Charts Community 14.2.0 graphs (`static/charts.js`, `GET /api/analytics`): Live demo 2x2 Analytics card,
  userA's dashboard cost / usage / risk (D-108). AG Studio not used: commercial + Enterprise-only + npm-only.
- `/user` rewritten as userA's own view (second person, the AG Grid subscriptions with Keep / Cancel) (D-110).
- Light/dark toggle at the top right; CSS tokens, AG Grid theme modes and AG Charts themes all follow it (D-109).
- Checks: 221 tests, ruff clean, `ui_check.py` covers the charts, the toggle (remembered after reload), the tabs.

### Judge navigation (2026-11-10)
- Top-bar tabs (Live demo, userA's dashboard, Shop, Health, API docs) and the new `/user` page (D-107).
  `tests/test_user_page.py`; `ui_check.py` also clicks through the tabs.

### 10-day trial + cancellation email (2026-11-10)
- Trial 10 days, first charge Day 11, notice 3 days; deadline Day 7, timer Day 6, check-in Day 5; proof Day 11
  (`sim-jump-11`). KPI $524.88, risk 87 (D-103).
- Cancel = PayPal first, then an LLM-drafted cancellation email (validated, template fallback) in an editable
  preview: Send (demo outbox) / Open in Gmail / Close. Never sent without a click; Send is idempotent (D-104/105).
  New: `app/core/notices.py`, `app/routes/notices.py`, `app/static/email.js`, `data/fixtures/llm/cancellation_email.json`,
  `tests/test_notices.py`. Video scenes updated (still 172 s, D-106).
- Checks: full pytest + ruff clean; `python scripts/ui_check.py` drives the new flow (email preview, empty To
  disables Send, Gmail link, three Start-demo answers) with no console errors.
- After pulling: `make reset` (and `make seed` in sandbox mode) so runtime data uses the 10-day plan.

### Story simplification (2026-11-10)
- Spec section 2 rewritten: Day 0 approve (companion summary, risk 87, "I'll check with you before your trial
  runs out.") -> Day 5 check-in (Zapier email/SMS + in-app, Keep / Cancel) -> Cancel (demo path) / Keep / no
  answer (Day 6 auto-cancel, R2) -> Day 15 blocked charge (now Day 11, see above). KPI **$524.88**.
- Removed: John, Lumen, Framewise, price-rise flow + demo button, add-on, user switcher, yearly advice, renewal
  reminders (pages, fixtures, seed data, chat tool, tests, docs). Kept on purpose: see D-091.
- Code: `actions.confirm_cancelled` (notice + "Done" for both cancel paths, D-094), `timers` (new Day 0 / Day 5
  wording, Keep -> `kept_day`, D-093/D-095), `demo_seed` (usage only, D-096), risk weights retuned (D-092).
- Checks: 189 tests pass (`-m 'not sandbox'`), ruff clean, `python scripts/tasks.py ui-check` drives the new
  story in headless Chromium with no console errors.
- After pulling this: run `make reset` (old runtime data still has Framewise/Lumen/John; D-099). In sandbox mode,
  `make seed` now creates only the Penwright product and plan.

### Milestone 7 notes (2026-11-10)
- Default `pytest` excludes the `sandbox` marker (pyproject `addopts`); `python -m pytest -m sandbox` opts in.
- Webhooks: `app/routes/webhooks.py`; sandbox verification uses `app.state.verify_webhook` (wired in `main.py`
  from the SDK backend's REST client) and needs `PAYPAL_WEBHOOK_ID`. Status changes from both the webhook and the
  poller go through `escalation.apply_status`.
- Milestone 8 (Zapier): `Notifier` already retries 3x and maps 2xx to `accepted` (tested with respx); what remains
  is a real Catch Hook URL in `.env`, the Zap itself (or `docs/ZAPIER_SETUP.md`), and `render.yaml` + deploy.

### Milestone 6 notes (2026-11-10)
- UI: `app/static/app.js` (window.SG: api, toast, confirm card, refresh fan-out), `dashboard.js` (KPIs, alerts,
  timeline, notices, demo bar, 5 s polling), `grids.js` (all AG Grid code), `chat.js` (SSE over fetch).
  View model for the grid/timeline: `GET /api/view/subscriptions?user=` (`app/routes/views.py`).
- Chat: `app/core/agent.py` (loop, max 8 steps, audit `llm_call`), `app/core/chat_tools.py` (tools, R5 checks),
  `app/routes/chat.py` (`POST /api/chat` SSE: text / tool / card / done / error events), mock scripts in
  `app/llm/mock_chat.py` + `data/fixtures/llm/chat.json`.
- Selector contract: every id is present (static in templates, the rest rendered by JS); `scripts/ui_check.py`
  exercises most of them, which is useful for milestone 9's `check_scenes.py`. `--shots DIR` saves screenshots.
- Duplicate test ids by design: `alert-keep` / `alert-cancel` appear on several alerts, so scope them inside
  `alert-price-rise` in the video recorder.

### Milestone 5 notes (2026-11-10)
- Core: `app/core/services.py` (`Services` = settings, store, gateway, notifier, policy; on `app.state.services`),
  `policy.py`, `actions.py` (propose card / confirm / cancel_one / Layer 2 handoff), `timers.py`, `escalation.py`
  (`tick`), `alerts.py` (idempotent `send_alert`, notices), `signup.py` (`register_active` + Day-0 protection),
  `demo_seed.py`, `usage.py`; `app/clock.py` (`advance`). Notifier: `app/integrations/notify.py`.
- APIs for milestone 6's UI: `/api/alerts?user=` + `POST /api/alerts/{id}/act {user_id, action}` (cancel-type
  actions return `{"confirm": card}`; the UI's tap then calls `/api/agent/confirm`), `/api/agent/propose`,
  `/api/agent/confirm`, `/api/timers`, `/api/notices`, `/api/kpis`, `/api/subscriptions/{id}/keep|essential`,
  `/api/demo/advance?days=N|to_day=N`, `/api/demo/price-rise`, `/api/demo/toggle-fair-trial/{merchant}`.
- The chat tools in milestone 6 should call `propose_cancel` / `compare_billing` / `usage` helpers, never do maths.
- Not done yet (milestone 7 list): corner case 27 (exports > limit end the trial early) has no code yet; corner
  cases 1 (expire APPROVAL_PENDING after 3h), 6 (webhook dedupe), 8 (non-USD guard) still need tests/notes.
- `make reset` (tasks.py) wipes runtime only; the demo seed happens on the next app start (or `/api/demo/reset`).

### Milestone 4 notes (2026-11-10)
- Review pipeline: `app/core/auditor.py` (orchestration), `crosscheck.py`, `risk.py` (weights, deadlines),
  `patterns.py` (library, injection regex, fallback), `savings.py` (`year_one_cost`). Types in `app/review_types.py`.
- `app.state.llm` / `app.state.capture` / `app.state.auditor` are built in `create_app`. Reviews are stored with
  typed `ReviewData`; register links the companion's `review_id` to the new subscription (milestone 5 uses
  `deadlines` from that review to create timers).
- Mock chat fixtures live in `data/fixtures/llm/chat.json` (empty until milestone 6).

### State after milestone 2 (2026-11-10)
- Venv at `.venv` (Python 3.14.4); deps from `requirements.txt` and Playwright Chromium are installed.
- Run: `python scripts/tasks.py dev` (or `make dev`). Tests: `python scripts/tasks.py test`. Lint: `... lint`.
- Code map: `app/config.py` (Settings + `validate_settings`), `app/models.py` (all JSON file models),
  `app/store.py` (`JsonStore`: `load`, `edit`, `aedit`, `alocked`, `reset`), `app/core/audit_log.py`
  (`store.audit.append(actor=..., event=..., ...)`, `verify`, `query`, `to_csv`), `app/routes/{pages,api,demo,deps}.py`,
  `shop/routes.py` + templates. Merchant plans and billing cycles live in `data/seed/merchants.json`.
- Shop checkout: `_checkout.html` renders a mock "Approve with PayPal (sandbox mock)" button
  (`data-testid=shop-paypal-btn`) that **does nothing yet**. Milestone 3 wires it to the mock gateway; milestone 4 adds companion.js.
- `/api/demo/reset` exists; `advance`, `price-rise` and `toggle-fair-trial` come in milestone 5.

### Since milestone 2 (2026-11-10)
- PayPal layer uses `paypal-server-sdk` 2.4.0 + httpx helpers (`paypal_rest.py`), commit `301e4c6`.
  Gateway, mock PayPal, MCP backend and checkout/register API exist and are tested; milestone 3 is
  NOT done yet (seed script + sandbox cancel check remain).
- Prices and terms are `.env` variables (`app/pricing.py`, D-015). **`seed_sandbox.py` must build
  plans from `settings.pricing`**, and when the prices differ from an already-seeded plan it must
  create a new plan (PayPal plans can't change billing-cycle structure) and update `sandbox_ids.json`.

### Milestone 3 notes (2026-11-10)
- Seed: `python scripts/tasks.py seed [--demo-subs] [--no-auto-approve] [--headless]`. Live check:
  `python scripts/tasks.py sandbox-check` (opens a headed browser and logs in as the personal sandbox buyer).
- Penwright intro price is a paid TRIAL cycle (D-031). SDK `get_billing_plan` takes a positional id.
- Buyer approval: the first consent click right after login can land early, so it retries up to 3 times.
- Leftover `APPROVAL_PENDING` sandbox subscriptions from failed runs are harmless; PayPal expires them.

### Before / during milestone 3
1. **Blocked on the user:** install the APIMatic PayPal context plugin (`npx context-plugins install paypal`,
   or `claude plugin marketplace add context-plugins/plugin-marketplace` then
   `claude plugin install paypal@context-plugins --scope user`). The session permission policy blocked
   running external npx code. After installing, query it and reconcile `docs/PAYPAL_SDK_NOTES.md`.
2. **Needs credentials:** PayPal sandbox REST app (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`), a sandbox
   personal buyer account, then `export PAYPAL_ACCESS_TOKEN=$(scripts/paypal_token.sh)` and start the
   PayPal MCP server. Run `list_tools()` and rewrite `docs/PAYPAL_TOOLS.md` with the exact names and schemas.
3. The SDK has no products controller and no `PayPal-Request-Id` on cancel / update-pricing (DECISIONS D-010):
   use httpx for those.
4. Mock gateway: persist to `subscriptions.json` through `store.aedit`, audit every call with `transport="mock"`,
   and support `?fail=cancel`.
5. Check that `PAYPAL_AUTOPAY_URL` (the sandbox autopay page) still exists.
6. Milestone 4: re-verify the LLM model ids in `.env.example` (DECISIONS D-028), using the claude-api skill for Anthropic.

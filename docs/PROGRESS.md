# SubGuard build progress

Milestones from `docs/BUILD_PROMPT.md` section 12. Tick each one only after its check passes and it is committed.

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
- [ ] **9. Demo-video tooling, code only** (section 13). Don't record or render a video.
  - *Check:* `make demo-video-check` passes.
- [ ] **10. Docs + submission files**, then a final review against section 15.
  - *Check:* every item in section 15 "Definition of done" is satisfied.

## Notes for next session

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

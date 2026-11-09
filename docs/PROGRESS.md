# SubGuard build progress

Milestones from `docs/BUILD_PROMPT.md` section 12. Tick each one only after its check passes and it is committed.

- [x] **1. Preflight.** Run `claude mcp list`; check Python >= 3.11, Node >= 18 and `npx`; install the APIMatic PayPal context plugin; write `docs/PAYPAL_TOOLS.md` and `docs/PAYPAL_SDK_NOTES.md`; create `docs/DECISIONS.md`.
  - *Check:* tool versions confirmed; the three docs exist.
  - Done 2026-11-10 (commit `3a05a3e`). Python 3.14.4, Node 24.15, npx 11.14. **Open:** the APIMatic plugin isn't installed, and the PayPal MCP isn't started (DECISIONS D-003).
- [x] **2. Scaffold + JSON store + audit log + dummy shop.**
  - *Check:* `make setup && make dev` serves `/`, `/shop` and `/shop/penwright`; the store and audit log tests pass (atomic write, corrupt-file recovery, hash chain).
  - Done 2026-11-10 (commit `a1843af`). Ran via `python scripts/tasks.py setup` / `dev` (no `make` on this machine). Every page returned 200, with no console errors in headless Chromium. 47 tests passing; ruff clean.
- [ ] **3. PayPal layer (mock + SDK + MCP) + seed.**
  - *Check:* gateway tests pass in mock mode; in sandbox mode `make seed` creates the plans, and a cancel shows `CANCELLED` both via the SDK and via the PayPal MCP server.
- [ ] **4. LLM providers + fine-print review + companion overlay.**
  - *Check:* the Penwright preflight returns >= 7 findings including `NOTICE_PERIOD`, `TERMS_MISMATCH` and `PROMPT_INJECTION_ATTEMPT`; risk 87 +/- 5; deadline day 7; every quote is verbatim. Lumen scores 15 +/- 5. The provider contract tests pass for Anthropic, OpenAI and mock.
- [ ] **5. Policy, timers, escalation, clock.**
  - *Check:* Story A days 0 -> 5 -> 6 -> 15 -> 21 and Story B days 0 -> 10 -> 27 produce the right alerts, actions and audit log entries (correct actors and rule ids); `test_policy.py` covers R1-R7.
- [ ] **6. UI (AG Grid) + chat agent.**
  - *Check:* the full Story A works in mock mode in the browser with no console errors; the chat produces a confirmation card for Framewise with **$228/yr**; the audit log grid exports CSV.
- [ ] **7. Tests and hardening.**
  - *Check:* `test_scenario.py` runs Story A + B end to end in mock mode and asserts **$872.76**; every corner case in section 8 has a test or a doc note; optional `@pytest.mark.sandbox` smoke test (skipped without credentials); ruff is clean.
- [ ] **8. Sponsor wiring.** Zapier (real hook in sandbox + outbox in mock), `render.yaml` + deploy.
  - *Check:* Zapier delivery works (or outbox in mock); the Render URL is in the README.
- [ ] **9. Demo-video tooling, code only** (section 13). Don't record or render a video.
  - *Check:* `make demo-video-check` passes.
- [ ] **10. Docs + submission files**, then a final review against section 15.
  - *Check:* every item in section 15 "Definition of done" is satisfied.

## Notes for next session

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

# SubGuard build progress

Milestones from `docs/BUILD_PROMPT.md` section 12. Tick each one only after its check passes and it is committed.

- [x] **1. Preflight.** Run `claude mcp list`; check Python >= 3.11, Node >= 18 and `npx`; install the APIMatic PayPal context plugin; write `docs/PAYPAL_TOOLS.md` and `docs/PAYPAL_SDK_NOTES.md`; create `docs/DECISIONS.md`.
  - *Check:* tool versions confirmed; the three docs exist.
  - Done 2026-11-10 (commit `3a05a3e`). Python 3.14.4, Node 24.15, npx 11.14. **Open:** the APIMatic plugin isn't installed, and the PayPal MCP isn't started (DECISIONS D-003).
- [ ] **2. Scaffold + JSON store + audit log + dummy shop.**
  - *Check:* `make setup && make dev` serves `/`, `/shop` and `/shop/penwright`; the store and audit log tests pass (atomic write, corrupt-file recovery, hash chain).
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

(none yet)

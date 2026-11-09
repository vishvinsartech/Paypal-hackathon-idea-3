# Decisions

Ambiguities resolved with the simplest reasonable option. Newest at the bottom.

## Environment

- **D-001 Python 3.14 venv.** The dev machine's default is Python 3.14.4 (3.11 and 3.12 are also
  installed). Every dependency installed cleanly on 3.14. The code targets 3.11+ (no 3.12+-only syntax).
- **D-002 No `make` on Windows.** This machine has no `make`. The `Makefile` is the canonical
  interface (judges on macOS/Linux). `scripts/tasks.py` mirrors every target
  (`python scripts/tasks.py setup|dev|test|...`) so Windows works without installing anything.
- **D-003 APIMatic plugin and PayPal MCP.** In milestone 1 the session's permission policy blocked running
  external npx code, so `PAYPAL_SDK_NOTES.md` was written from the installed `paypal-server-sdk`
  2.4.0 source. The user then installed the APIMatic Context Plugin for PayPal (v0.4.1). The
  installer put it under `~/.context-plugins/vscode/paypal` (VS Code Copilot), not in Claude Code.
  It documents a different SDK (see D-011), so it's used **for reference only**: the general
  guidance (OAuth caching, error boundaries, idempotency, testing with a stubbed transport).
  `PAYPAL_TOOLS.md` was later re-verified against the live PayPal MCP server (1.11.0, 28 tools).
- **D-004 `claude` CLI.** It isn't on PATH. The binary bundled with the VS Code extension
  (Claude Code 2.1.319) was used for `claude mcp list`. `scripts/mcp_setup.sh` assumes `claude` is on PATH.

## PayPal

- **D-010 httpx for SDK gaps** (spec 5 requires each case to be recorded). `paypal-server-sdk`
  2.4.0 has (a) no Catalog Products controller, (b) no `PayPal-Request-Id` parameter on
  `cancel_subscription` / `update_billing_plan_pricing_schemes`, (c) no per-call custom headers (so
  no `PayPal-Auth-Assertion`), and (d) no webhook signature verification. Those calls go through
  `app/integrations/paypal_rest.py` (httpx), with its own cached client-credentials token (refreshed
  and resent once on a 401, with the same `PayPal-Request-Id`). In partner mode every merchant-side
  call goes through it, since only REST can carry the assertion header. The same cached token feeds
  the PayPal MCP server. Everything else uses the SDK.
- **D-011 PayPal SDK: `paypal-server-sdk` (PyPI), pinned to 2.4.0.** Reason: it's the official PayPal
  package, judges get a plain PyPI install, and it's still APIMatic-generated. The plugin's git SDK
  (`paypal` 2.29 from github.com/context-plugins/paypal-python-sdk) was considered and rejected.
- **D-012 Sync SDK in an async app.** `paypal-server-sdk` is synchronous (`requests`), so every SDK
  call runs in a worker thread via `asyncio.to_thread`. The event loop never blocks on PayPal.
  On a 401 the SDK client is rebuilt (fresh token) and the call retried once. The SDK's own retries
  (`max_retries=2`) apply only to GET/PUT. Cancel retries live in the gateway and reuse the same
  `PayPal-Request-Id`.
- **D-013 Mock PayPal state in `mock_paypal.json`.** PayPal's side of the world (plans with current
  prices, subscription statuses) lives in its own file. `subscriptions.json` stays SubGuard's view
  (owner, consent snapshot, timers). That keeps "what PayPal says" and "what we recorded" separate,
  as the spec's "PayPal is the source of truth" needs.
- **D-014 Extra modules.** `app/integrations/paypal_types.py` (shared error and view types, so the
  backends don't import each other), `app/integrations/paypal_rest.py` (D-010) and
  `app/routes/subscriptions.py` (checkout + register endpoints). They keep the spec's files under
  about 300 lines.

## Storage and app structure (milestone 2)

- **D-020 One uvicorn worker.** JSON storage + one in-process lock only works in a single process,
  so `dev` and Render run `--workers 1`.
- **D-021 Lock design.** One `threading.RLock` (re-entrant, so the audit log can append inside an
  edit) plus one `asyncio.Lock`. Async code uses `store.aedit()` / `store.alocked()`, which take the
  asyncio lock first, because the RLock alone can't separate two coroutines on the same thread.
  Plain reads don't lock: `os.replace` makes every read see a complete file.
- **D-022 JSON file shape.** Every list file is `{"items": [...]}` so it validates as one Pydantic
  model. All models live in `app/models.py` (not in the spec's layout; it keeps `store.py` small).
- **D-023 Audit hash.** `hash = sha256(canonical JSON (sorted keys, no spaces) of the entry minus
  "hash")`; genesis `prev_hash` is 64 zeros. Secrets and emails are masked before hashing, so
  nothing sensitive ever reaches disk.
- **D-024 Reset keeps archives.** Reset wipes `data/runtime/` except `sandbox_ids.json` and the
  archived `audit_log.<ts>.jsonl` files (the spec says archives are never deleted).
- **D-025 Fair Trial defaults.** All three seed merchants start as `fair_trial_member: true` (Layer 1
  is the main demo path). The demo toggle switches any merchant to Layer 2.
- **D-026 Merchant emails use `.example`.** For example `cancel@penwright.example`: a reserved
  domain, so we use no real brand and no deliverable address.
- **D-027 `/shop/<merchant>/app` records usage on GET.** It's a side effect on GET, but it is exactly
  "opening it records a usage event", and it keeps the video recorder simple.
- **D-028 Model defaults in `.env.example`.** `claude-opus-5-5` and `gpt-5` for now. Re-verify both
  ids in milestone 4 before writing the providers.

- **D-015 Demo prices and terms are configurable in `.env`** (user request). `app/pricing.py`
  defines every rate and term number (Penwright trial days, intro price and months, step-up price,
  add-on price, notice days, export limit; Framewise price and rise price; Lumen monthly and yearly;
  the currency), with the spec's values as defaults and validation (positive, at most 2 decimals).
  A bad value stops startup with a message naming the variable. `data/seed/merchants.json` keeps
  only names and emails; plans are built from pricing. The shop pages render the same values, so
  the page text and the PayPal plan can't drift apart (otherwise the reviewer would rightly flag
  TERMS_MISMATCH). Changing prices applies after `make reset` (`/healthz` warns until then);
  existing subscriptions keep their consent snapshot. **Tests use the defaults**, so the spec's
  assertions ($872.76, risk 87/15, deadline Day 7) stay valid; money maths in later milestones must
  read from `settings.pricing`, never literals.

## Not used in v1 (sponsor tools)

- **Bryntum:** a CSS timeline is enough for a prototype.
- **Elastic:** about 20 dark-pattern examples fit in a JSON file.
- **KERNEL:** our dummy site is local, so local Playwright is simpler than a cloud browser + tunnel.
- **Postman:** the README + FastAPI's `/docs` are enough.
- **Astropods:** not needed to run or judge the prototype.
- **Channel3:** product search doesn't fit this project.

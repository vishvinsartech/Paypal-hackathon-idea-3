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
- **D-028 Model defaults in `.env.example`.** `claude-opus-5-5` and `gpt-5`. Milestone 4: `claude-opus-5-5`
  re-verified as the current default Claude model (Anthropic API reference, cached 2026-10-06). `gpt-5`
  was not re-verified (no OpenAI docs access in this session); it's only a default, set `OPENAI_MODEL`.

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

## Seeding (milestone 3)

- **D-029 Seed idempotency.** `make seed` reuses a stored product if PayPal still has it, and a stored
  plan only if PayPal's copy is ACTIVE and its billing cycles + currency match `settings.pricing`
  exactly. Anything else gets a new plan and `sandbox_ids.json` is updated (PayPal can't change a
  plan's cycle structure). Request ids are content-derived, so a lost `sandbox_ids.json` doesn't
  duplicate what PayPal still remembers. Seed checks only the PayPal settings (no LLM key needed).
- **D-030 Milestone 3 cancel check is a script.** `scripts/sandbox_cancel_check.py`
  (`python scripts/tasks.py sandbox-check`) creates two subscriptions, approves them as the sandbox
  buyer with Playwright, cancels one via the SDK transport and one via the MCP transport, and reads
  both back over both transports. The pytest `sandbox` smoke test comes in milestone 7.
- **D-031 Penwright intro price is a paid TRIAL cycle (deviates from spec 7.1).** PayPal rejects plans
  with more than one REGULAR cycle (`MULTIPLE_REGULAR_BILLING_CYCLE_NOT_SUPPORTED`, verified live). So
  `penwright-pro` is TRIAL 14 days $0 -> TRIAL 3 x 1 month $24.99 -> REGULAR unlimited $49.99, the
  PayPal-native way to do intro pricing. `first_charge_day` counts only the leading *free* cycles
  (still Day 15) and `first_paid_price` is the first priced cycle (still $24.99), so every key number
  is unchanged.
- **D-032 Sandbox buyer approval uses Playwright on PayPal's page** (`scripts/sandbox_buyer.py`),
  with `return_url` on 127.0.0.1 intercepted by Playwright, so the app doesn't need to be running.
  It needs a sandbox *personal* account; the business account that owns the REST app is refused.

## Fine-print review (milestone 4)

- **D-034 Add-on checkout in sandbox is a second PayPal button.** If the add-on box is ticked, the
  sandbox shop shows a second Subscribe button for the add-on after the main approval
  (`shop/static/checkout_sandbox.js`); the spec allows this simplification. The PayPal button only
  renders after the companion's "Continue to PayPal" (`subguard:continue` event).
- **D-040 Two capture implementations.** Mock mode uses `StaticCapture`: it fetches our own `/shop`
  pages through the ASGI app and parses the HTML + `shop.css` (font size, colour -> WCAG contrast,
  `display:none`, collapsed `<details>`, default-checked boxes, one level of same-site "terms" links).
  Deterministic, no browser, works on Render. This replaces the spec's stored `captures/*.json`
  fixtures, because prices come from `.env` (D-015) and a stored capture would drift. Sandbox mode uses
  `PlaywrightCapture` (live Chromium: screenshot + bounding boxes), falling back to the static capture
  with a logged warning. Only `/shop/<merchant>[/terms]` paths can be captured (no arbitrary URLs).
  Elements marked `data-subguard-ignore` (the companion's own note) are skipped.
- **D-041 Structured output, not forced tool calls.** Current Claude models reject forced `tool_choice`,
  so the Anthropic reviewer uses `output_config.format` (json_schema); OpenAI uses `response_format`
  json_schema with `strict: true`. One hand-written schema (`REVIEW_JSON_SCHEMA`) serves both. Money
  hints from the model are parsed leniently and then discarded: code recomputes all money from PayPal.
  Effort `low` for both review and chat, so the review fits the companion's 20-second timeout. Opus 5.5 /
  Sonnet 5.5 / Fable 5.1 calls opt into the server-side refusal fallback (`fallbacks: "default"`).
- **D-042 Provider contract tests use SDK fakes, not respx.** The installed `anthropic` 2.x and `openai`
  3.x SDKs run on `httpx2`, which respx can't intercept. The tests inject fake clients that return real
  SDK response types (`BetaMessage`, `ChatCompletion`), which still exercises request building and
  response parsing in each adapter. No network.
- **D-043 Risk weights.** Each clause type counts once: AUTO_RENEW 10, NOTICE_PERIOD 5, INTRO_PRICE_STEP_UP 4,
  HARD_CANCEL 4, TERMS_MISMATCH 4, PRECHECKED_ADDON 3, EARLY_TRIAL_TERMINATION 3, HIDDEN_TEXT_STYLE 1,
  PROMPT_INJECTION_ATTEMPT 0, CLEAR_TERMS 0. Plus the spec's style penalties (+8/+8/+10/+6), money factor
  `min(15, year-one cost / 50)` from the PayPal plan (Penwright 524.88 -> 10.50), and a library bonus of
  2 points per distinct dark-pattern type the page matches by regex (cap 10). Severity is shown, not
  scored, so the score doesn't depend on how a model rates severity. Penwright = 34 + 32 + 10.50 + 10 =
  86.5 -> **87** (half-up); Lumen = 10 + 4.80 = **15**. Injection weighs 0, so a page can't buy a lower or
  higher score with hidden instructions. TF-IDF (scikit-learn) only labels each clause with its nearest
  same-type library example.
- **D-044 Code-added findings.** Besides verifying every quote (whitespace-normalised substring; drop +
  one retry), code adds PROMPT_INJECTION_ATTEMPT (regex over all captured text, hidden included),
  HIDDEN_TEXT_STYLE (from style signals) and TERMS_MISMATCH (PayPal cross-check) when the model missed
  them. The cross-check flags: a reviewer-read first charge day/amount that differs from the plan, a
  PayPal price the page never states, and prominent checkout text (>= 18px, readable) that shows no price
  PayPal will charge (Penwright's "$0 today" headline). A no-trial plan is charged at signup (day 0).
- **D-045 Notice days come from the verified quote.** `notice_days` is parsed from the NOTICE_PERIOD
  quote ("at least 7 days") when present, else the model's value, else 0. First charge day always
  comes from the PayPal plan.

## Policy, timers, escalation, clock (milestone 5)

- **D-050 Where confirmation tokens come from.** Spec R3 says tokens are "issued by `/api/agent/confirm`", but
  7.3 says `propose_cancel` returns the card + token and Confirm calls `/api/agent/confirm`. We follow 7.3:
  `POST /api/agent/propose` (and alert buttons `cancel` / `remove_addon`, and the chat's `propose_cancel` in
  milestone 6) issue the token with the card; `POST /api/agent/confirm` consumes it and runs policy -> gateway.
  Tokens are masked in the audit log.
- **D-051 R2 warning delivery.** "Delivered" = the in-app alert was stored (`in_app: shown`) AND (a Zapier
  channel accepted, OR Zapier is mocked/unconfigured, OR Zapier failed after retries = "down"); the basis is
  logged as `zapier_accepted | zapier_mocked | zapier_down_in_app_only`. So only an in-app failure blocks
  (corner case 12, tested with `Notifier.fail_in_app`). "24 sim-hours" = warned on an earlier sim day.
  Info alerts are in-app only; warning/urgent/action_needed alerts also go to the user's email/SMS channels.
- **D-052 Blocked timers retry, then fail.** If R2 blocks a due timer only because the warning isn't
  delivered yet, the timer stays PENDING: the warning is retried each day and the timer re-checked. On the
  billing day it becomes FAILED with an urgent alert. R6 (essential) -> timer CANCELLED + urgent alert.
  A failed PayPal cancel -> FAILED + Layer 2 handoff (notice + ACTION NEEDED link), never "Done".
- **D-053 Scripted demo usage.** The demo seed writes usage events with `source: "seed"` (Priya: Framewise
  Days -2, 3, 10 and Penwright Days 2, 4; John: Lumen Days 1-9 and 12). Only days <= today count, so the
  story's numbers ("opened Penwright twice", "3 times this month", "9 of the last 10 days", "2 weeks")
  are reproducible; opening `/shop/<merchant>/app` still adds live events on top.
- **D-054 Demo seed subscriptions.** In mock mode with `DEMO_SEED=true` (default; tests turn it off),
  first start and Reset create Priya's Framewise (signup Day -5, so it renews Day 25 and the Day 21 price
  rise lands before it) and John's Lumen monthly (Day 0, reviewed by the real pipeline: risk 15). Penwright
  is not seeded: Priya subscribes through the shop + companion in the demo. Sandbox mode seeds nothing.
- **D-055 Which subscriptions get a safety timer.** A trial timer is created only for plans that start with a
  free cycle (a trial before the first charge), using the linked review's notice days. Honest no-trial plans
  (Lumen, Framewise) get no auto-cancel timer, only renewal reminders (3 days before, if unused 14+ days)
  and price watching. A price-rise timer (fire = billing day - 1) is created only with
  `auto_cancel_price_rises` on; the price-rise alert itself is its warning.
- **D-056 Manual cancel for Layer 2 merchants** returns `action_needed` (written notice sent + one-tap
  Automatic payments link) instead of calling PayPal, matching "everything except the final click".
- **D-057 "Money protected"** = the sum of `protected_year_usd` over subscriptions SubGuard cancelled (by the
  user's confirmation or a timer): the year-one cost of the PayPal plan *at cancel time* (Framewise after the
  rise: 12 x $19 = $228). Story A gives 524.88 + 119.88 + 228.00 = **$872.76**.
- **D-058 Billing days in the sim.** On a subscription's `next_billing_day`, an ACTIVE subscription logs a
  simulated `charge_due` and moves to the next cycle; a CANCELLED one logs `charge_blocked` and gets the
  "First charge due today: blocked" alert. The R4 rate limit is kept in process memory (1 worker, D-020).

## UI + chat agent (milestone 6)

- **D-060 AG Grid version.** AG Grid Community **36.2.0** (UMD bundle from jsDelivr, pinned). 36.3.0 was the npm
  `latest` but less than a week old on 2026-11-10, so we took the newest release older than two weeks. API checked
  in the bundle: `agGrid.createGrid`, `themeQuartz.withParams` (theming API, no CSS file), `setGridOption`
  (`rowData`, `quickFilterText`), `exportDataAsCsv`. `grids.js` also calls
  `ModuleRegistry.registerModules([AllCommunityModule])` defensively. No Enterprise features, no licence key.
- **D-061 Chat history lives in the browser.** `/api/chat` is stateless: the page sends the previous turns as plain
  text (last 12), and tool traffic is not replayed. No chat storage on the server; every tool call and LLM call
  is in the audit log (provider, model, latency, tokens, never the prompt).
- **D-062 Mock chat = small script interpreter.** `data/fixtures/llm/chat.json` scripts are tool-call steps plus a
  final `say` template whose `{tool.field}` slots are filled only from tool results (R7). The mock picks the
  subscription by the script's merchant or by matching words in the message. Two or more matches -> a clarifying
  question (corner case 33). Any other message gets the "mock mode" fallback.
- **D-063 Unknown tools are policy blocks.** A model calling a tool that isn't in `tools_schema.py` (e.g. a direct
  `cancel_subscription`) gets an error result and an audited R1 `blocked` decision. Ownership errors inside
  tools are audited as R5 blocks; `propose_cancel` goes through the same `issue_token` checks (R4/R5).
- **D-064 Evidence view = live page, not a screenshot.** In mock mode the capture is static HTML (no screenshot),
  so `/subscriptions/{id}` shows the merchant page in a same-origin iframe with each finding's
  `evidence_testid` outlined in red. Hidden text (the injection line) can't be outlined and is listed in the
  findings grid instead.
- **D-065 Alerts become "handled" when their subscription is cancelled.** After a successful cancel, open alerts
  for that subscription that offer keep/cancel/remove-add-on buttons are acknowledged, so stale buttons
  disappear. The "Done" alert (Restart trial) is created later and stays actionable.
- **D-066 `schedule_reminder`** stores `Reminder`s in `state.json` (no new file). `tick()` sends each one once, as
  an info alert, on its day.
- **D-067 Browser check.** `python scripts/tasks.py ui-check` (`scripts/ui_check.py`) starts its own mock server on
  a free port with a throwaway `DATA_DIR`, drives Story A through the real UI with Playwright, and fails on any
  console error. It needs the CDN, so it isn't part of `pytest`.

## Not used in v1 (sponsor tools)

- **Bryntum:** a CSS timeline is enough for a prototype.
- **Elastic:** about 20 dark-pattern examples fit in a JSON file.
- **KERNEL:** our dummy site is local, so local Playwright is simpler than a cloud browser + tunnel.
- **Postman:** the README + FastAPI's `/docs` are enough.
- **Astropods:** not needed to run or judge the prototype.
- **Channel3:** product search doesn't fit this project.

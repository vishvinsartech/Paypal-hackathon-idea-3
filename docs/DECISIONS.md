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
  so the server always runs one worker (how that's enforced since D-100: uvicorn's default + `WEB_CONCURRENCY=1`
  on Render).
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

- **D-034 Add-on checkout in sandbox is a second PayPal button.** *(Superseded by D-090.)* If the add-on box is ticked, the
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
- **D-043 Risk weights.** *(Weights retuned in D-092.)* Each clause type counts once: AUTO_RENEW 10, NOTICE_PERIOD 5, INTRO_PRICE_STEP_UP 4,
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
- **D-053 Scripted demo usage.** *(Now Penwright only: D-096.)* The demo seed writes usage events with `source: "seed"` (userA: Framewise
  Days -2, 3, 10 and Penwright Days 2, 4; John: Lumen Days 1-9 and 12). Only days <= today count, so the
  story's numbers ("opened Penwright twice", "3 times this month", "9 of the last 10 days", "2 weeks")
  are reproducible; opening `/shop/<merchant>/app` still adds live events on top.
- **D-054 Demo seed subscriptions.** *(Superseded by D-090.)* In mock mode with `DEMO_SEED=true` (default; tests turn it off),
  first start and Reset create userA's Framewise (signup Day -5, so it renews Day 25 and the Day 21 price
  rise lands before it) and John's Lumen monthly (Day 0, reviewed by the real pipeline: risk 15). Penwright
  is not seeded: userA subscribes through the shop + companion in the demo. Sandbox mode seeds nothing.
- **D-055 Which subscriptions get a safety timer.** *(Renewal reminders and price watching removed: D-090.)* A trial timer is created only for plans that start with a
  free cycle (a trial before the first charge), using the linked review's notice days. Honest no-trial plans
  (Lumen, Framewise) get no auto-cancel timer, only renewal reminders (3 days before, if unused 14+ days)
  and price watching. A price-rise timer (fire = billing day - 1) is created only with
  `auto_cancel_price_rises` on; the price-rise alert itself is its warning.
- **D-056 Manual cancel for Layer 2 merchants** returns `action_needed` (written notice sent + one-tap
  Automatic payments link) instead of calling PayPal, matching "everything except the final click".
- **D-057 "Money protected"** *(Now $524.88: D-090.)* = the sum of `protected_year_usd` over subscriptions SubGuard cancelled (by the
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

## Tests and hardening (milestone 7)

- **D-070 Unapproved subscriptions are never stored** (corner case 1). Register answers 202 and stores nothing
  until PayPal says ACTIVE, so there is no "pending" list for us to expire after 3 hours; PayPal expires its own
  `APPROVAL_PENDING` subscriptions. Recorded as a doc note in `docs/CORNER_CASES.md`.
- **D-071 One status-change path.** `escalation.apply_status` is used by both the poller (each tick) and
  `/webhooks/paypal`. It does nothing when the status is unchanged, so webhook + poller (or two webhooks) for the
  same change log one `status_sync`. Webhook event ids are also deduped (last 500 kept in `state.json`). In
  sandbox mode an unverified signature -> 400 + `webhook_rejected` audit entry.
- **D-072 Currency guard.** `Pricing.money(amount, currency)` formats in the plan's currency. The Money protected
  KPI sums only the demo currency; other currencies are returned as `other_currencies` and shown next to it,
  labelled. The demo is all USD.
- **D-073 Early trial end (exports).** The fake app page has an "Export a document" button
  (`POST /shop/<merchant>/app/export`, a usage event of kind `export`). Each tick, a PENDING trial timer whose
  review has an `EARLY_TRIAL_TERMINATION` clause compares exports since signup with the clause's number ("more
  than N"). Over the limit -> one urgent alert (Cancel now / Keep) and the timer's `deadline_day` moves to today.
  The timer still fires on its day, because R2 forbids firing without a warning 24 sim-hours earlier.
- **D-074 Sandbox smoke test is opt-in.** `tests/test_sandbox_smoke.py` is marked `sandbox`, and `pyproject.toml`
  sets `addopts = -m 'not sandbox'`, so plain `pytest` never calls PayPal. `python -m pytest -m sandbox` runs it
  (read-only: OAuth + the seeded plans' billing cycles); it skips without credentials or seeded plan ids.

## Sponsor wiring (milestone 8)

- **D-080 Render: mock mode, no browser download.** The hosted demo runs `APP_MODE=mock`, where reviews use the
  static HTML capture (D-040), so the build is just `pip install -r requirements.txt`; no `playwright install`
  (it's slow and large on the free plan). Python is pinned to 3.12.10 with `PYTHON_VERSION`, and a clean copy was
  tested locally on 3.12.10 (build command, start command, Story A in the browser). One worker (D-020). JSON files
  live on Render's temporary disk: each restart or deploy re-seeds the demo, and the README says so. Secrets are
  `sync: false` entries only. The blueprint deploys branch `main`.
- **D-081 Zapier routes fictional recipients to the owner.** The demo people and merchants have `*.example` emails
  and `+1555` numbers, so the Zap sends to the owner's own inbox and phone and keeps the demo recipient in the
  text (`docs/ZAPIER_SETUP.md`). "Accepted" = the Catch Hook returned 2xx; delivery itself is in Zap History.
- **D-082 Zapier only in sandbox mode.** Mock mode always writes `data/runtime/outbox/`, even when a hook URL is
  set, so the hosted mock demo never sends real messages. In sandbox mode without a hook, startup logs a warning,
  and the startup audit entry records `notify: outbox|zapier`.

## Story simplified to userA + Penwright (2026-11-10)

- **D-090 One persona, one merchant.** At the user's request the demo story (spec section 2) is now userA +
  Penwright Studio only. Removed from the story, UI, code, fixtures, tests and docs: John, Lumen Notes, Framewise,
  the Day 21 price-rise flow (`/api/demo/price-rise`, price watching, "Keep at $19"), the pre-ticked add-on
  (plan `penwright-ai-pack`, checkbox, add-on offer, `addon_of`), the user switcher, monthly-vs-yearly advice
  (`compare_billing_options`) and renewal reminders. "Money protected" is now **$524.88** (3 x 24.99 + 9 x 49.99).
  Corner cases 35 and 36 are marked removed; 28 is tested at the formula level; 31 uses a test-only second user.
- **D-091 Kept although no demo flow uses it.** The safety rules are unchanged, so `policy.py` keeps R2's
  price-rise condition and the `auto_cancel_price_rises` setting (still unit-tested). The PayPal gateway keeps
  `update_pricing` (tested). `PRECHECKED_ADDON` stays a generic clause type in the review and the dark-pattern
  library. The chat's `schedule_reminder` stays (it isn't a renewal reminder). The Penwright export clause stays
  on the page: it wasn't in the remove list, and corner case 27 still tests it.
- **D-092 Risk weights retuned.** Removing the add-on removed 13 points (PRECHECKED_ADDON 3 + pre-ticked box 10),
  so Penwright fell to 74. New weights stress the story's real traps: NOTICE_PERIOD 5 -> 12, HARD_CANCEL 4 -> 8,
  INTRO_PRICE_STEP_UP 4 -> 6. Penwright = 44 + 22 + 10.50 + 10 = 86.5 -> **87**. Honest terms
  (AUTO_RENEW + CLEAR_TERMS, $240/yr) still score 15. The "model obeys the injection" test now asserts a
  code-only score >= 40 (was 50; it's 48 without the pre-ticked box).
- **D-093 Check-in wording.** Day 0 alert title: *"I'll check with you before your trial runs out."*; its body
  names the Day 5 check-in and the Day 6 timer, which is how the timer is "shown at creation" (R2). Day 5 uses the
  requested sentence verbatim and adds *"If I don't hear back, I'll cancel it tomorrow so you're not charged."*
  so the user knows about the auto-cancel before it happens. Buttons: Keep / Cancel. Alert kind stays `reminder`
  (test id `alert-trial-check`).
- **D-094 One "done" step for both cancel paths.** `actions.confirm_cancelled` runs after any confirmed PayPal
  cancel, from the user's tap or the timer: it sends the written notice (SHA-256 stored) and *"Done. You won't be
  charged."* Before, only the timer path sent the notice. Alert kind `cancelled` (was `auto_cancelled`),
  idempotent per subscription; in-app only for a tap, also email/SMS for the timer.
- **D-095 Keep.** Sets `Subscription.kept_day`, marks pending timers KEPT and acknowledges open Keep/Cancel
  alerts, so there are no further prompts. On Day 15 a kept subscription just logs `charge_due` (no alert).
- **D-096 Demo seed = usage only.** `DEMO_SEED` now writes only userA's scripted Penwright opens (Days 2 and 4),
  so "You've opened it twice" is reproducible. No subscriptions are seeded; the dashboard starts empty and userA
  approves the trial herself on Day 0.
- **D-097 Mock chat scripts.** "Should I keep Penwright?" calls list_subscriptions, get_usage,
  get_savings_estimate and review_subscription, then answers with code numbers (opens, $524.88, Day 7) and no
  card: the decision stays hers. "Cancel Penwright" gives the confirmation card.
- **D-098 scenes.json before milestone 9.** `demo-video/scenes.json` follows the new story (10 scenes, 172 s, cap
  175 s). The rest of the video tooling is still milestone 9. `tests/test_scenes.py` checks the duration cap,
  125 wpm per scene and that every target test id exists. New test ids: `companion-summary`,
  `companion-promise`, `alert-timer-set`, `alert-trial-check`, `alert-done`, `audit-filter`, `chat-close`.
- **D-099 Old config and data.** `PENWRIGHT_ADDON_PRICE`, `FRAMEWISE_*` and `LUMEN_*` are gone from
  `.env.example`; leftover keys in a local `.env` are ignored (`extra="ignore"`). Runtime data from before this
  change (Framewise/Lumen merchants, John) is stale: run `make reset` (the pricing fingerprint warning says so).

## Server start (2026-11-10)

- **D-100 One standard start command.** Locally: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  --reload` (README Quick start shows it directly, since `make` may not exist on Windows). `make dev` and
  `python scripts/tasks.py dev` run exactly that with the venv's Python; `dev-sandbox` adds `APP_MODE=sandbox`.
  `dev` no longer forces mock: the mode comes from the environment / `.env` (default mock), same as the bare
  command. There's no separate launcher script. Render runs `python -m uvicorn app.main:app --host 0.0.0.0
  --port $PORT` (no `--reload`). **Still one worker** (D-020): no command passes `--workers`, uvicorn defaults to
  1, `--reload` never forks workers, and `render.yaml` pins `WEB_CONCURRENCY=1` because uvicorn reads that
  variable as its default worker count and a host could set it.

## Animated dashboard + Start demo (2026-11-10)

- **D-101 Start demo runs in the browser, through the normal APIs.** `app/static/autoplay.js` resets the demo,
  runs the preflight review, creates + mock-approves + registers the Penwright subscription, then advances one
  day at a time. It pauses when the check-in alert appears (Day 5 with default terms; the timer would fire on
  Day 6) and shows it as a modal: Keep / Cancel / "Don't answer". Answers go through `/api/alerts/{id}/act` like
  the alert buttons, so Cancel still shows the confirmation card (R1/R3) and "Don't answer" lets the Day 6 timer
  act under R2. Then it runs to the first charge day. No new server endpoint; mock mode only (sandbox
  approval needs the real PayPal button, so the button is disabled there).
- **D-102 Motion.** CSS keyframes + small JS: staggered card entrance, count-up KPIs with a glow, day-chip bump,
  new alerts slide in, the timeline's today line slides, new timeline rows grow in, risk bars grow, a breathing
  dot on ACTIVE pills. AG Grid: `animateRows`, `enableCellChangeFlash` on the subscriptions grid, new audit rows
  flashed with `flashCells` (audit grid keyed by `seq`), theme `rowHoverColor` and
  `valueChangeValueHighlightBackgroundColor` (both checked in the pinned 36.2.0 bundle). Everything is off under
  `prefers-reduced-motion`. Panels re-render every 5 s, so animations are only applied to things that are new.

## 10-day trial + cancellation email (2026-11-10)

- **D-103 New Penwright terms.** Defaults are now a 10-day trial (first charge Day 11) and 3 days' written notice
  (`PENWRIGHT_TRIAL_DAYS=10`, `PENWRIGHT_NOTICE_DAYS=3`). Deadline maths unchanged: 11 − 3 − 1 = Day 7, timer
  Day 6, check-in Day 5; proof (blocked charge) on Day 11, so the demo bar's jump button is `sim-jump-11`. KPI
  stays $524.88, risk 87. The PayPal plan keeps the D-031 shape (TRIAL 10 days $0 -> paid TRIAL 3 x 1 month
  $24.99 -> REGULAR unlimited $49.99) because PayPal rejects two REGULAR cycles; the request's "REGULAR 3 x 1
  month" is billed identically. `seed_sandbox.py` and the mock fixtures read the plan from `.env` pricing, so
  they pick the new terms up automatically (run `make reset`, and `make seed` in sandbox mode). Day 5 message:
  *"Your Penwright trial ends on Day 10, but your real last day to cancel is Day 7. You've opened it twice. Do you
  want to keep it?"* plus the D-093 "If I don't hear back..." sentence; trial end = billing day − 1.
- **D-104 Cancellation email replaces the auto-sent notice (supersedes the notice part of D-094).** After any
  confirmed PayPal cancel (tap or timer) `actions.confirm_cancelled` alerts *"Cancelled in PayPal. You won't be
  charged."* and `core/notices.create_draft` asks the LLM (`draft_cancellation_notice`) for the email. Code
  validates it (name, account email, PayPal id, date, the stored review's NOTICE_PERIOD quote verbatim, "cancel"
  + "confirm" + "writing", under 120 words, no links); any problem or LLM error -> the fixed "standard template".
  The draft is stored in `notices.json` with `status: draft` and is **never sent without a click**. Layer 2
  handoffs (corner case 4) also only draft it. No follow-up step after the email.
- **D-105 Send / Open in Gmail (demo only).** Both finalize the email once: final to/subject/body, `edited`
  (compared with the draft), SHA-256 of the final body, `sent_at`, `sent_via` (`demo_outbox` |
  `gmail_compose_link`), written straight to `data/runtime/outbox/` (not through the Notifier, so never Zapier in
  sandbox mode). A second click returns the stored email (idempotent; also safe under the store lock). Opening
  Gmail counts as handing it over: we can't know if she pressed Send in Gmail. The Gmail URL is built in the
  browser at click time (so the popup isn't blocked) with `encodeURIComponent`, and on the server with the same
  safe set; over 1800 characters -> "Too long for Gmail link; copy the text instead" + Copy, nothing recorded.
  Empty To or Body disables Send (and the API returns 400). "Close" keeps the server draft; unsent edits are kept
  per browser in localStorage. "Today's date" is the real UTC date (the sim clock has no calendar).
- **D-106 Video.** `07_cancel` grows to 30 s (confirm -> email preview -> Send); `03_companion` 32 -> 30 s and
  `06_chat` 20 -> 16 s, so the total stays 172 s (cap 175).

## Judge navigation (2026-11-10)

- **D-107 Page tabs + userA's dashboard.** The top bar gets tabs next to the mode/AI badges: **Live demo** (`/`,
  with the demo bar), **userA's dashboard** (`/user`), and **Shop ↗**, **Health ↗**, **API docs ↗**, which open in
  new tabs so the live demo window stays put. The Shop tab replaces the "View dummy website" button and keeps its
  `view-shop` test id. `/user` is server-rendered from the store; its day-by-day feed (`core/activity.py`) maps
  audit events to plain English and skips low-level ones (PayPal HTTP calls, tokens, LLM calls), so every line is
  backed by a logged event (R7). It re-fetches itself every 4 s (skipped while a dialog is open or the tab is
  hidden) so it follows a demo running in another tab. R5: `?user=` only shows that user's data. `timer_created`
  audit entries now include `reminder_day`.

## Analytics, userA's own view, light/dark theme (2026-11-10)

- **D-108 AG Charts Community, not AG Studio.** AG Studio (the AG Grid team's dashboard library, v3.1.0) was
  requested. It is Commercial-licensed (45-day trial, then a licence), depends on `ag-grid-enterprise` and
  `ag-charts-enterprise`, and ships for npm bundlers only, with no UMD/CDN build. That breaks three project
  rules: Community edition only with no licence key, vanilla JS from pinned CDNs, and no build step. So the graphs
  use **AG Charts Community 14.2.0** (MIT, the chart engine AG Studio is built on), pinned on jsDelivr like AG Grid
  36.2.0. 14.3.0 was released 2026-11-04, under two weeks ago, so 14.2.0 is pinned. v14 API checked against
  the docs: `axes` is an object keyed `x`/`y`, and modules are registered with `AllCommunityModule`.
  `GET /api/analytics` (`core/analytics.py`) supplies the data: cumulative first-year cost from the PayPal
  billing cycles (Decimal strings; the browser only plots them), the review's risk breakdown, audit-log entries
  by actor and by day, and trial opens per day with the deadline and first-charge lines. Before any signup the
  cost chart previews the Penwright plan (`preview: true`). Live demo: a 2x2 Analytics card (cost, risk, activity
  by day, who acted). userA's dashboard: cost, usage, risk. Actor colours are fixed and match the timeline badges.
- **D-109 Light / dark theme.** A toggle at the top right sets `<html data-theme>` and `data-ag-theme-mode`. An
  inline `<head>` script applies the saved choice before first paint, so there's no flash. The choice is a
  per-browser convenience in localStorage (try/catch). The default stays **dark**, so the demo video and
  screenshots don't change with the OS setting. CSS uses the same tokens with light values. AG Grid uses one
  `themeQuartz` with `"light"` and `"dark"` params. AG Charts re-renders with `ag-default` / `ag-default-dark` on
  the `sg-theme` event. The shop (fictional merchant) keeps its own look.
- **D-110 userA's dashboard is written to her.** `/user` now speaks in the second person ("Hi userA, here's your
  SubGuard", "You tapped Cancel", "Cancelled your subscription after you confirmed"). Her subscriptions are the
  same AG Grid as the live demo (Keep / Cancel with the confirmation card), and the server-rendered table is gone.
  The live refresh swaps only the `[data-live]` sections that changed, and refreshes the grid and charts through
  their APIs.

## Focus UI: presenter view vs userA's view (2026-11-10)

- **D-111 Check-in advice is a code rule, labelled as advice.** userA's Day 5 check-in shows her usage ("Opened
  twice in 5 days (last on Day 4).") and *"SubGuard suggests: cancel. You decide."* The suggestion comes from code,
  not the LLM: fewer than 3 opens during the trial means "cancel", otherwise "keep". The reason quotes the same code
  numbers the chat uses (opens and the first paid year's cost from the PayPal plan), so nothing is invented (R7).
  It never acts: Keep / Cancel stay her taps, and Cancel still needs the confirmation card.
- **D-112 Live demo = control room, userA's dashboard = product.** No duplication between them. Live demo: demo bar,
  greeting, the email-ready banner, step tracker, **Money protected** only, alerts, timeline and the audit log grid.
  The analytics card, the subscriptions grid, the emails list and the other KPIs are removed. The Fair Trial toggle
  (Layer 2) stays in the markup but hidden (`layer2-controls`; README explains how to use it). userA's dashboard: a
  subscription card (status, risk, "Site says … · Real last day to cancel …", next charge, timer, Keep / Cancel,
  View fine-print review) replaces the one-row grid, an empty state before signup, the Day 5 check-in, the Day 11
  proof banner, two KPIs (Money protected, Cancelled in PayPal), the AG Charts (only here) and the activity list as
  an AG Grid (`GET /api/activity`, external filter). On both pages the health dots, Health and API docs move into
  the footer's Developer menu, and the footer gets "Fictional merchant · PayPal Sandbox · MIT license · GitHub"
  (`REPO_URL`). Restart trial is gone everywhere: the cancelled alert has only "Review email", and Keep after
  the timer fired just says it's already cancelled. The cancel flow has no extra pop-ups: success toasts are
  skipped when the email preview opens, the "cancelled" alert isn't toasted, and "Email sent" shows in the preview
  only. The chat is a shared partial on both pages, collapsed, with Penwright-only suggestions, and is out of the
  video. Video: 9 scenes, 169 s, switching between the two pages (`goto`).

## Real PayPal sandbox approval in the demo (2026-11-10)

- **D-113 Real approval, live status card.** Sandbox checkout: the companion first, then the PayPal JS SDK
  Subscribe button. `createSubscription` asks **our server** to create the subscription (`/api/checkout/create`
  with `js_sdk: true`, SDK + `PayPal-Request-Id`, no redirect URLs), because PayPal's console says client-side
  `actions.subscription` is deprecated; the button then opens PayPal's own approval window. `/register` still
  waits for ACTIVE (corner case 2). The **"Subscribed via PayPal ✓" card** (`static/paypal-card.js`,
  `data-testid="paypal-subscribed"`) is standalone so it works on the shop too. It calls
  `GET /api/subscriptions/{id}/paypal` (R5), which does `gateway.verify()`: a live GET of the subscription and its
  plan through the **full backend** (SDK in sandbox), not MCP, because MCP tool results carry no HTTP headers and
  the card shows PayPal's `paypal-debug-id`. Status, plan name and billing cycles are PayPal's, never our JSON; if
  PayPal and our copy disagree the card shows PayPal's and says so. Each read writes `paypal_subscription_verified`
  (transport, PayPal debug id, plan debug id, status, plus the request id of our create, or of the cancel once
  cancelled). Create now also writes `paypal_subscription_created` (request id -> PayPal subscription id), and
  every backend's `cancel_subscription` returns the success debug id. After a cancel the card shows CANCELLED from
  PayPal, the cancel call's ids (over MCP labelled "SubGuard ref", since no `PayPal-Request-Id` header is sent
  that way) and "View in PayPal sandbox" -> `PAYPAL_AUTOPAY_URL`
  (`https://www.sandbox.paypal.com/myaccount/autopay/`; verified: logged out it redirects to sign-in with
  `returnUri=/myaccount/autopay`, logged in as the buyer it is PayPal's "Manage your automatic payments" page;
  the merchant shows there under the sandbox business account's display name). Dashboards re-read from PayPal only
  when our status for a subscription changes, not on every 4-5 s refresh. Mock mode: the button reads "Mock PayPal
  approval (run in sandbox mode for the real PayPal window)", and the card says "Mock PayPal (simulated)" with no
  sandbox link. `scripts/sandbox_ui_check.py` (`make sandbox-ui-check`) tests the whole path with the sandbox
  buyer. PayPal opens its window from its cross-origin iframe, so the check waits on the browser context's new
  page, not `page.expect_popup`. It always cancels what it created, and without an LLM key runs PayPal-only by
  building the sandbox app with a placeholder key (the companion then shows the labelled basic review). The real
  app's startup check is unchanged. Re-seeded `penwright-pro` for the 10-day terms (`P-3B864581XR137251MNLZRFOI`).
- **D-114 Hand-recorded PayPal clip in the video.** The recorder runs in mock mode and can't show PayPal's real
  window, so scene `03b_paypal_approval` has `"type": "clip"` -> `demo-video/clips/paypal_approval.mp4`
  (gitignored), at most 15 s, no actions. `build_video.py` inserts it after `03_companion`, trims every segment to
  its scene's duration (never extends), and refuses a cut over `max_total_seconds` (175 s) or 3 minutes.
  `check_scenes.py` warns (doesn't fail) on a missing clip, and the mock build skips that scene, unless
  `--require-clips`. To make room, six scenes lost 2-4 s and two narrations a sentence or word (165 s with the
  clip, 150 s without). Logic shared in `demo-video/videolib.py` and unit-tested without ffmpeg. Recording
  instructions: `demo-video/README.md`. The automated recorder and voice-over are still milestone 9.
- **D-115 Key dates as calendar dates.** Each card on userA's dashboard has a "Key dates" list: Subscribed
  (the real date and time SubGuard recorded the PayPal approval, `registered_at`), check-in, auto-cancel, real
  last day to cancel, trial end (site says), first charge, price rise, then Cancelled / Kept. A sim day N maps to
  `registered_at + (N - signup_day)` days (`app/core/sub_dates.py`), so the dates match the Day buttons. A cancel
  shows its sim day's date with the real time of the PayPal call. The server writes UTC text in
  `<time datetime>` tags and `user.js` shows them in the viewer's time zone; the live refresh compares server
  HTML with server HTML so the localized text doesn't cause a swap every tick. The PayPal card adds PayPal's
  own `start_time`. It doesn't show PayPal's `next_billing_time`: PayPal bills at start + 10 days (the "Day 10"
  date), while the spec counts the first charge as Day 11, so the two would differ by a day.
- **D-116 Start demo in sandbox mode.** The Start button no longer turns itself off in sandbox mode. Steps 1-2 run
  in a real Penwright window that Start opens (it opens `about:blank` during the click so pop-up blockers allow
  it). With `?autodemo=1` the shop plays userA: it opens the Terms and clicks PayPal, the companion's real-LLM
  review stays up for 6 s, then it clicks Continue. `POST /api/checkout/demo-auto-approve` (sandbox only, needs
  `PAYPAL_SANDBOX_BUYER_*`, one at a time) creates the subscription with the SDK and approves it as the sandbox
  buyer in a visible Playwright browser (`DEMO_APPROVE_HEADED`, slow_mo 120 ms). It waits for ACTIVE and
  registers it, audited as `demo_auto_approve` with the buyer's email masked. The window shows the live PayPal
  card, sends each stage to the control room with `postMessage` (same origin only), and closes itself. The
  stepper then continues exactly as in mock mode (timer, days, the Day 5 Keep/Cancel, Day 11). This is a
  subscribe, not a cancel, so R1-R7 are unchanged. The buyer helper moved to
  `app/integrations/sandbox_buyer.py` (the scripts keep a shim). Its consent step is now one loop that clicks
  whichever consent button PayPal shows ("Continue", then "Agree & Subscribe") until the redirect: about 28 s
  instead of about 115 s. The demo seed (scripted usage only) now runs in both modes, so the check-in says
  "opened it twice" in sandbox mode too, and zero usage reads "You haven't opened it yet."
- **D-117 The presenter confirms in PayPal (replaces D-116's auto-approve).** After the companion's Continue,
  the Penwright window shows **Subscribe with PayPal** and waits for a click. `POST
  /api/checkout/demo-paypal-window` (sandbox only, one at a time) creates the subscription and opens PayPal's
  approval page in a visible browser window that logs in with `PAYPAL_SANDBOX_BUYER_*`. It then waits up to 5
  minutes for a person to click Continue / Agree & Subscribe; SubGuard never clicks consent. A popup from the
  page itself can't be filled in, because PayPal's login is on another site, so the window is a separate
  Playwright browser. Outcomes: approved (PayPal redirected back), so it waits for ACTIVE and registers;
  "Cancel and return", window closed, or timeout give a 409 with a plain message and nothing registered.
  Subscribe can be clicked again, and the control room shows each stage. Audited as `demo_paypal_window` with
  the outcome. `DEMO_APPROVE_HEADED` is removed. `open_for_confirmation(headless=, presenter=)` exist only for
  scripted checks. **Fix:** on Windows, `uvicorn --reload` serves on a SelectorEventLoop, which can't start
  Playwright's driver subprocess (`NotImplementedError`). Subscribe failed with a 500 and the live page capture
  quietly fell back to the static one. Both now run on their own loop in a worker thread
  (`app/integrations/own_loop.py`, a Proactor loop on Windows). OpenAI errors now keep OpenAI's reason (for
  example "organization must be verified to use gpt-5").
- **D-118 Subscription history grid replaces "Your timeline"; key dates fold away.** On userA's dashboard the
  AG Grid now lists one row per subscription (`GET /api/subscription-history`, R5: owner only, newest first):
  name + plan, Active/Cancelled, price, subscribed / free-trial-ends / real-last-day-to-cancel (Day N + local
  date), next charge, outcome, safety timer, risk, latest event (tooltip: every event from the audit log) and an
  event count. Tools: quick search, status filter, Clear filters (search, column filters, sort), CSV export.
  Rows reuse the card's data (`card()`), so grid and card never disagree. `/api/activity` stays as an API.
  Each card's "Key dates" list is a closed `<details>` dropdown; the live refresh keeps it open once opened.
- **D-119 Fine-print check speed (companion's 20 s limit).** Sandbox reviews sometimes showed "SubGuard couldn't
  check this page" because capture (~2-3 s) + PayPal plan fetch + the LLM call (11.7-18.6 s in the audit log) ran
  one after another. Capture and plan fetch now run side by side (`asyncio.gather` in `/api/review/preflight`).
  `OPENAI_REASONING_EFFORT` is optional and omitted by default: measured on gpt-5.4 (Penwright, risk 87 every
  run), default/none took 8-10 s and ~1k output tokens, while "low" took 17-19 s and ~1.6k tokens. The LLM
  call's time is mostly writing the JSON answer, and OpenAI's speed varies, so a slow call can still pass 20 s;
  the browser limit (20 s) is shorter than the server's worst case (2 x LLM_TIMEOUT_SECONDS). Open item.
- **D-120 Manual shop visits log in as the sandbox buyer too.** In sandbox mode, when
  PAYPAL_SANDBOX_BUYER_EMAIL / _PASSWORD are set, the shop's "Continue to PayPal" shows the same "Subscribe with
  PayPal" button as the live demo (D-117): the server opens PayPal's approval page in its own window, already
  logged in, and a person clicks Agree & Subscribe (SubGuard never clicks consent). The page only gets a
  `data-buyer-login="1"` flag; the credentials stay on the server. Without them, PayPal's own JS SDK pop-up is
  used, as before. `/api/checkout/demo-paypal-window` takes `source: demo|shop`, audited in `details.source`.
  Static JS/CSS is now served with `Cache-Control: no-cache` (`FreshStatic` in `app/main.py`): Chrome had kept
  the old checkout_sandbox.js and opened PayPal's own pop-up (with Chrome's saved email) instead.
- **D-121 Compact PayPal strip and a "What SubGuard did" table on the live demo.** Re-running Start demo without
  Reset stacked one full PayPal card per run. Now both dashboards show only the latest run as a one-line strip
  (plan, id, live status, cycles on one line, "View in PayPal sandbox"); start time, request ids and debug ids
  sit under "details", and earlier runs fold into "N earlier runs" one-line rows (still read live from PayPal).
  On the live demo the strip sits inside the step-by-step card. The shop keeps the full card (D-113). The audit
  card now defaults to "What SubGuard did": the current run only (userA's latest registered subscription, its
  fine-print review, and anything blocked for her since), one plain row each, reusing userA's activity wording
  plus every policy decision (allowed or blocked). Built server-side (`app/core/run_summary.py`,
  `GET /api/audit-log/summary`); the audit log itself is unchanged. "Show full log" reveals the raw AG Grid with
  filter and CSV export; the chain badge stays visible.
- **D-122 Sidebar sections on userA's dashboard.** The page was one long scroll. A sidebar now shows one section
  at a time: Overview (KPIs, subscription cards, "Verified with PayPal"), Analytics (AG Charts), History (AG Grid),
  Messages (badge: message count) and Emails (badge: drafts to review). Anything that needs userA (the Day 5
  check-in, "email ready", the Day 11 proof banner) is pinned above the sections, so it can't be hidden. The URL
  hash names the section (`/user#analytics`), so reloads and links keep it; no storage. Below 860 px the sidebar
  becomes a sticky, scrollable strip. Sections are plain `hidden` blocks: the live refresh (`[data-live]` by id)
  and the charts/grid (ResizeObserver) are unchanged. `app/static/user-nav.js`. Video scene 09 clicks Analytics
  before highlighting the cost chart.

## v3 Phase 1: correctness and story logic (2026-11-11, docs/FIX_PLAN.md)

- **D-130 Persona Priya.** userA is now **Priya**, a freelance writer who pays for apps with PayPal: user id `priya`,
  display name "Priya", and a new `User.full_name` ("Priya Sharma") that the cancellation email uses ("Name: Priya
  Sharma"). Email `priya@subguard-demo.example`. `/me` is an alias of `/user`; `/user` keeps working. Route defaults
  stay a literal (`user: str = "priya"`), as they were with `usera`, instead of a new constant: one sed, no new
  imports. Old runtime data holds `usera`: run `make reset`.
- **D-131 Users see calendar dates, never sim days (B2).** The companion builds its text from a code-made `display`
  block in the `/api/review/preflight` response (`sub_dates.companion_display`): offsets from sign-up plus short
  UTC dates from the real "now" ("Nov 18"). So opening the shop on Day 11 reads exactly like Day 0. Alerts,
  Priya's card, the chat and the subscription page use `sub_dates.day_text(sub, day)` (`registered_at + (day -
  signup_day)`, as in D-115). Cross-check rows say "11 days after you start". Absolute sim days stay internal
  (timers, audit, presenter-only controls).
- **D-132 Act by vs what the terms allow (D6).** `Deadlines.terms_last_day = first_charge - notice` (Penwright: 8),
  filled by a validator for reviews stored before. `real_cancel_deadline_day` (7) keeps its meaning as "act by",
  SubGuard's one-day margin. One wording everywhere, from `sub_dates.act_by_text`: "Act by Nov 18 (the terms allow
  Nov 19)". For a subscription the terms' day is always act-by + 1.
- **D-133 No answer -> written notice, only with an opt-in (D7; narrows D-104).** The companion shows an unticked
  box "If I don't answer, send the cancellation email for me." On Continue it posts
  `POST /api/reviews/{id}/consent` (allowed only while the review isn't linked to a subscription), and sign-up
  copies it into `ConsentSnapshot.auto_send_notice`. Every sign-up path (shop, sandbox window, Start demo) passes
  `review_id`, so one place covers them all. Ticked: when the timer cancels, the draft is finalised as written
  (`sent_via = "auto_on_timer"`, demo outbox), audited `notice_auto_sent`, actor `timer`, rule R2, decision
  allowed. D-104's "never sent without a click" still holds for every other case. Unticked: on the act-by day, a
  cancelled subscription whose email is still a draft gets one `notice_unsent` alert: "Your cancellation email
  isn't sent yet. The terms need it by <date>." with **Review email**. It also applies after a user-tap cancel
  whose email was closed unsent. No new PayPal writes.
- **D-134 The Day 11 proof is SubGuard's check (B8).** On the first-charge day SubGuard does a fresh
  `gateway.verify()` (live GET through the full backend in sandbox, the mock state in mock mode). The
  `charge_blocked` entry stores PayPal's status (`status_after`), `paypal_debug_id`, `result`
  (`no_active_subscription` | `still_active` | `error: ...`) and `details.checked_by = "SubGuard"`. The audit actor
  stays `system`, because the CLAUDE.md actor list has no SubGuard value; the activity feed shows "SubGuard". Text:
  "Checked PayPal: no active subscription, so no charge can be taken." If the read fails it says it couldn't reach
  PayPal and claims nothing (R7). If PayPal still shows ACTIVE, the alert is urgent.
- **D-135 Charges avoided (D10).** `savings.charges_avoided` sums the first paid price (from the consent snapshot's
  PayPal cycles) of each subscription SubGuard cancelled (user or timer): Penwright **$24.99**. It's the KPI's main
  value, with "up to $524.88 in year one" (`money_protected`, unchanged) as the subtitle. `/api/kpis` returns both
  plus `year_one_text`. The test ids are kept (`kpi-protected`, `user-protected`), and new ones added
  (`kpi-year-one`, `user-avoided`, `user-year-one`). The confirmation card still shows $524.88/yr until U12.
- **D-136 No "clear terms" next to dark patterns (B10).** `patterns.drop_clear_terms_if_risky` runs after both the
  AI and the basic path. It drops `CLEAR_TERMS` when any type other than CLEAR_TERMS, AUTO_RENEW or
  PROMPT_INJECTION_ATTEMPT is present. The score doesn't change, because CLEAR_TERMS weighs 0.
- **D-137 "What SubGuard did" and the step tracker follow the data (B3, B4).** The summary table now draws as soon
  as the page loads. Before, it waited for the next 5 s refresh because `audit-summary.js` registers after the
  first refresh had already run, so it looked empty after a manual run and on mobile. The dashboard's first
  refresh now runs on `DOMContentLoaded`. The 7 steps are derived server-side from the subscription's audit events
  (`app/core/steps.py`) and ship with `GET /api/audit-log/summary` as `steps`. The page applies every non-pending
  step on each refresh, so clicking through by hand ticks them. Start demo keeps its transient in-progress marks,
  and its texts match the derived ones.
- **D-138 Trial timeline: fixed Day 0-14 view, five dots (B7).** Signed up · Check-in · Act by · Trial ends · First
  charge, each with its calendar date. Positions, states (done | today | upcoming | blocked) and alternating label
  sides come from `sub_dates.trial_dots` in `/api/view/subscriptions`. `app/static/timeline.js` draws them on the
  live demo, and a Jinja macro draws the same markup on Priya's card. The step-up is text built from the cycles:
  "$49.99/month from month 4". The old Day 0-31 axis, its 8 px markers and the legend are gone. In Phase 3 (U7) it
  moves onto the merged card.
- **D-139 Toasts, chat entry, chat chips (B5, B6, B11).** Toasts stack top right at 72 px under the top bar,
  auto-dismiss after 6 s, and keep `aria-live`. "Ask SubGuard" (icon + label, `data-testid="chat-open"` kept) is in
  the top bar through a `topbar_actions` block on the pages that have the chat drawer; the floating button is gone.
  The chat shows three chips that stay visible: "Should I keep it?", "What happens if I do nothing?", "Draft my
  cancellation email". Mock scripts `do_nothing` and `draft_email` sit before `cancel`, so "cancellation email"
  doesn't propose a cancel. Their numbers and dates come from `review_subscription` (now with `check_in_on`,
  `auto_cancel_on`, `first_charge_on`, `act_by_text`, `terms_last_day`). `draft_email` explains when the draft
  appears; there's no draft tool, so it doesn't pretend to draft one (R7). The fallback names the chips instead of
  "switch to sandbox mode".
- **D-140 Companion opens at the top (B1).** The card is `max-height: min(720px, 90vh)` (border-box), a flex column
  with sticky header and footer and an internally scrolling middle. On open, focus goes to the title
  (`tabindex=-1`, `preventScroll`) and `scrollTop = 0`; Tab is trapped in the dialog and Esc closes it.
  `ui_check.py` asserts the risk badge is in view at 1440×900 and 390×844. The ≤ 640 px bottom sheet is U17
  (Phase 3).
- **D-141 Smaller Phase 1 calls.** The "Protected by SubGuard: cancel anytime" badge is removed for every merchant,
  not only Penwright (Quillnote won't be a member anyway). It was also the "cancel anytime" sentence the basic
  check had matched as CLEAR_TERMS. Penwright stays `fair_trial_member: true`. The subscription page
  (`partner-note`) and the README explain the partner connection. Usage is labelled "(from Penwright's app
  activity, simulated in this demo)" (D8), but not when there was no use. Narration got only the D6/B8/D10 wording
  (one shorter phrase in `03_companion` to stay within 125 wpm); Phase 5 rewrites the beats. **Deferred, as
  FIX_PLAN says:** B9 (mobile nav) goes with U10/U27 in Phase 3, and B12 (README facts) with S1 in Phase 4.

- **D-142 Quillnote, the second fictional merchant (A1).** An AI notes app, `fair_trial_member: false` (Layer 2),
  plan `quillnote-plus`: 7-day free trial, $12.99/month for 3 paid months, then $27.99/month, 72 hours' written
  notice. All of it comes from `.env` (`QUILLNOTE_*`, `app/pricing.py`); the page renders numbers in words
  (`app/core/durations.number_words`), so "seventy-two hours" follows the setting. Its traps are plain prose that the
  regex rules don't match: indirect auto-renewal ("simply carries on at $12.99 a month"), the step-up only in an FAQ
  answer, cancelling via "contact our account team", notice in words and hours. No hidden injection line. The headline
  says "free" with no price, so the code's PayPal cross-check still flags a mismatch on both paths. Checkout, terms
  page (`/shop/{merchant}/terms` is now one route), banner, and a plan in mock and in sandbox (`make seed` seeds
  every merchant). This relaxes D-090's "one merchant" on FIX_PLAN's instruction; the persona is still only Priya.
  First charge Day 8, terms' last day Day 5, act by Day 4, Layer 2 timer Day 2 (handoff, not a cancel).
- **D-143 Score calibration (A4).** Small grey text used to score three times (small font 8 + low contrast 8 +
  HIDDEN_TEXT_STYLE 1). Now "hard-to-read terms" is one +10, from any of: font < 11 px, contrast < 3:1, hidden text,
  or a HIDDEN_TEXT_STYLE finding. Hidden text that is itself an injection doesn't count (injection stays 0, D-043).
  AUTO_RENEW 10 -> 4 (every subscription renews). Library bonus 2 -> 1 point per matched type, max 5. To keep the
  real traps on top: NOTICE_PERIOD 20, HARD_CANCEL 14, INTRO_PRICE_STEP_UP 10, TERMS_MISMATCH 9,
  EARLY_TRIAL_TERMINATION 4, PRECHECKED_ADDON 3, HIDDEN_TEXT_STYLE 0 (it's the +10). Results: Penwright 86.5 -> 87
  (unchanged), Quillnote 73 (basic check 25), `tests/fixtures/honest_terms.html` about 6. The "model obeys the
  injection" floor is now 30 (was 40): code checks alone give 35.
- **D-144 The basic check runs with every review (A2).** `Auditor._assemble` does the code steps (injection, style,
  PayPal cross-check, deadlines, score) on one set of findings. `review()` runs it on the AI's findings and on
  `fallback_extract`'s, and stores the second as `ReviewData.basic` (types, clauses, notice days, act-by day, risk).
  The basic path gets no AI first-charge hints, so its cross-check has fewer rows. `ReviewData.ai_vs_basic()` lists
  each type with where it was found; `ai_only_risky` leaves out AUTO_RENEW, CLEAR_TERMS and injection. The
  subscription page shows the panel (`data-testid="ai-vs-basic"`) with notice period, act-by date (marked "too
  late" when the basic one is later) and both scores. Reviews stored before this have no `basic` and no panel.
- **D-145 Notice periods in words (A3).** `durations.duration_days` reads digits or number words (0-99) with hours,
  days or weeks; hours round up to whole days (72 h -> 3). The notice comes from a verified NOTICE_PERIOD quote only:
  code parses it; if the quote states a duration code can't read ("the third day before renewal"), the AI's
  `notice_days` is accepted. No verified notice quote -> 0, even if the AI gave a number (it used to be trusted).
  `ReviewData.notice_source` records which (`quote_digits` | `quote_words` | `ai` | `none`).
- **D-146 Layer 2 beat (A5).** Cancel on a non-member: `cancel_one` makes no PayPal write and calls
  `layer2_handoff`, which now returns the email draft's id, so the UI opens the email (without "Cancelled in
  PayPal") and Priya's page shows an **ACTION NEEDED** card (`action-needed`): "Open PayPal Automatic payments",
  "Review email", and "Waiting for PayPal to show … CANCELLED". While it's up, `user.js` calls
  `POST /api/subscriptions/{id}/check-paypal` every 3 s: one read-only `gateway.verify` GET (R5: owner only),
  `apply_status`, and on CANCELLED it acknowledges the handoff alerts, sends "PayPal shows Quillnote CANCELLED. You
  won't be charged." and audits `layer2_cancel_seen` with PayPal's debug id. `Settings.autopay_link` is
  `PAYPAL_AUTOPAY_URL` in sandbox and `/demo/paypal-autopay` in mock: a simulated Automatic payments page, labelled
  "Demo: simulated PayPal Automatic payments page", whose Cancel changes only the mock PayPal state. That's Priya
  acting in PayPal (audit actor `user`, `paypal_autopay_cancel`, decision n/a), not SubGuard, so no policy rule
  applies, and SubGuard learns about it only by reading PayPal, as in sandbox. The cancel result says "isn't a Fair
  Trial merchant, so you cancel it in PayPal: see ACTION NEEDED" and is no longer toasted as an error.
- **D-147 No mock labels on user surfaces (A6).** The top bar has one badge: "Demo data" (mock) or "PayPal Sandbox ·
  <model>" (sandbox); the separate "AI: mock" badge is gone. The chat drawer shows the model only in sandbox. The
  companion and subscription page show "AI review" (plus the model in sandbox). Emails say "Drafted by AI" or "a
  standard template" (`Notice.drafted_by` keeps the full label for the audit log; `Notice.merchant_name` is new, so
  the email preview names the right merchant). The mock checkout button reads "PayPal" with a small "Demo:
  simulated PayPal approval" note (the U21 wording, done now because the old text said "Mock"). The PayPal card
  says "read from the demo PayPal" instead of "fetched live … via mock". `/healthz` and the audit log keep the
  full detail. Delivery lines ("email: mocked") are U4, Phase 3.

- **D-148 One product view at `/` (U5, U7-U11).** `/` is Priya's SubGuard (`app/routes/user_page.py` +
  `home_view.py`, template `home.html`); `/user` and `/me` redirect there (307, query kept). The old live demo page
  and `/user` page are deleted (`dashboard.html`, `user.html`, `dashboard.js`, `user.js`, `audit-summary.js`,
  `timeline.js`). One merged card per subscription: header, a big cost line (`verdict.cost_line` from the consent
  snapshot), the act-by line (only while she can still decide), the five dots, one pair of actions, and a quiet
  "Verified with PayPal ✓ I-xxx · status read live" footer that reads PayPal when opened ("lite" mode, no ids).
  The Key dates box and the separate PayPal card are gone; `key_dates()` still dates the history rows. Right column:
  Charges avoided (before any cancel: "Nothing charged yet. Watching up to $524.88 in year one", never "up to $0"),
  Next decision (code, from the timers), and What SubGuard did (the 5 latest meaningful events from the audit log,
  chat questions left out, "Show all" opens the audit drawer). Empty state: one card + "Open the demo shop"; the
  right column is hidden. The `[data-live]` parts refresh from the page's own HTML (home.js); swaps are serialised
  so an action's refresh is never skipped.
- **D-149 The check-in is the card (U8).** The open reminder renders as a yellow "Keep it or cancel?" band at the
  card's top (usage, advice, delivery icons), and the card's buttons become the alert's Keep / Cancel trial. Only one
  pair on screen (tests count it). A Layer 2 handoff renders as a red band on its card and removes Keep / Cancel and
  the timer chip. Start demo no longer opens a modal: it waits for the alert to be acknowledged (and any dialog to
  close), or for "Don't answer (SubGuard acts on Nov 17)" in the presenter bar. The policy path is unchanged
  (alert Cancel -> propose -> confirmation token, R1/R3).
- **D-150 Companion order and "3 things to know" (U14-U18).** `app/core/verdict.py` builds, from the PayPal plan
  (code, not the LLM): the verdict line, the sub-line (step-up + year one), the PayPal check sentence, the 3 things
  (top severity, one per type; the injection note and TERMS_MISMATCH have their own boxes, and on a tie the things
  the verdict doesn't already say win: notice, hard cancel, early end), the deduplicated quotes and the cross-check
  rows failing first. `PayPalCheckRow.label` (new, "" on old reviews) is the row in plain words ("Price $24.99 shown
  only in fine print"). The AI summary moved inside the folded evidence. The `finding-<TYPE>` test ids stay on the
  visible lines (3 things, PayPal box, shield note); the folded quotes use `evidence-<TYPE>`. ≤ 640 px: bottom sheet.
- **D-151 Presenter bar (U6).** `_presenter.html`, fixed at the bottom with a dashed amber border, hidden unless
  `?demo=1` or D. Day scrubber 0-11 plus 0/5/6/7/11 and +1. Days only move forward (`/api/demo/advance` refuses to go
  back), so past-day buttons are disabled and dragging back says "Press Reset". The Fair Trial toggle is visible
  now and fixed to Quillnote. The 7-step tracker is a compact strip in the bar, still derived from the audit log (B4).
- **D-152 Confirm card and email modal (U12, U13).** `CardItem` gains `short_name`, `trial` and `next_charge_text`
  ("$24.99 on Nov 22", from the consent snapshot and next billing day). The card says "Cancel Penwright trial? You
  won't be charged $24.99 on Nov 22."; the year figure and "This can't be undone" are gone from it (the model keeps
  `warning` for the chat tool). After a cancel the card offers "Start a new trial" with "Penwright may not offer a
  second free trial." The email preview highlights `Notice.clause` (new field, the verbatim quote) with a mirrored
  backdrop behind the textarea, so it stays a plain editable textarea. "Open in my email app" is a `mailto:` link
  (new `POST /api/notices/{id}/mailto`, `sent_via="mailto"`, audit event `cancellation_email_app_opened`); Gmail is the
  secondary link.
- **D-153 Shop (U19-U22).** `/shop` is two product cards with a neutral one-line pitch (no spoiler, no tagline). The
  checkout pages got a hero, three features, a plan card and a PayPal-style button, with the scored text (headline,
  fine print, Terms) word for word. New text classes are dark on white and ≥ 13 px, and `@media` rules use only
  descendant selectors, because the static capture reads single-class rules: Penwright stays 87 and Quillnote 73
  (a test asserts it). After approval the page shows only "You're subscribed. Welcome to Penwright." and "Open
  SubGuard ↗"; the PayPal card left the merchant page (mock and sandbox).
- **D-154 Evidence page tabs (U23-U25).** Summary (verdict, 3 things, dates, AI vs basic, the three charts, the
  cancellation email) · Evidence (full-width page preview, then the findings grid) · PayPal check (cross-check
  failing row first, consent snapshot, the full PayPal card with request and debug ids) · Activity (meaningful
  events, then "Show raw log" with CSV). `/api/analytics?subscription_id=` scopes the charts to one subscription.
  "Why SubGuard flagged it" has four categories: Hidden deadline (notice, early end, auto-renew), Price jumps
  (step-up, mismatch, add-on, the money factor), Hard to cancel, Hard-to-read terms (styling, hidden text, injection,
  library bonus). The total still equals the score. Findings show plain labels, severity chips and "Found by:
  AI / Code check / PayPal".
- **D-155 Routine audit entries (U26).** `PayPalGateway._audit` adds `details.routine = true` to successful reads
  (`get_subscription`, `verify_subscription`, `verify_plan`, `get_plan`). They stay in the hash chain and the CSV.
  Every audit grid hides them by default with a "Show routine PayPal checks" box; summaries never showed them.
  Writes and errors are never routine.
- **D-156 Developer strings off user surfaces (U4).** Delivery: "App ✓ · Email ✓ · SMS ✓". The drafted-email
  activity line no longer names the drafter ("mock · fixtures"). Card cancels send "Cancelled on your SubGuard card"
  as the reason. Activity lines and the card status use calendar dates. PayPal ids and debug ids are on the
  evidence page's PayPal tab only.
- **D-157 Mobile, a11y, motion, vendoring (U27-U30).** At ≤ 640 px the top bar keeps logo, badge (no model name),
  and icon buttons on one line, the sections are a fixed bottom tab bar (B9), and the presenter bar sits above it.
  ui-check asserts no sideways scroll at 390 px. The companion keeps its focus trap and Esc. The evidence tabs are
  WAI-ARIA tabs (arrow keys). The theme toggle is an icon with a tooltip. `<html data-ready="1">` is set once no
  count-up is running (shots and the recorder wait for it), and `prefers-reduced-motion` turns animation off. AG Grid
  36.2.0 and AG Charts 14.2.0 are vendored in `app/static/vendor/` with their MIT licence files
  (`vendor/README.md`), and ui-check fails on any CDN request.

## v3 Phase 4: submission docs (2026-11-11, docs/FIX_PLAN.md)

- **D-158 Render: branch and sandbox-mode hosting (S5).** `render.yaml` deploys `prototype-v3` until the merge to
  `main`. Mock stays the default (`APP_MODE=mock`). For a sandbox-mode hosted demo, set `APP_MODE=sandbox` in the
  dashboard plus the secrets listed there (all `sync: false`, never in git): PayPal client id and secret, the LLM
  key, the sandbox buyer email and password, and optionally `PAYPAL_WEBHOOK_ID` and `ZAPIER_CATCH_HOOK_URL`. Render's
  disk is temporary, so `sandbox_ids.json` is lost on every start. In sandbox mode the start command runs
  `scripts/seed_sandbox.py` first. It's idempotent, because request ids come from the content and matching plans are
  reused. A failed seed is logged and the server still starts, so the error is visible in the app. Render has no
  `npx`, so the MCP transport falls back to the SDK (logged, as designed). Chromium isn't installed either, so live
  capture falls back to the static capture.
- **D-159 Docs layout (S1-S4).** The README covers the pitch, links, quick start, PayPal and AI usage, the
  architecture, real vs simulated, limitations, R1-R7, sponsor tools, tests and the licence. Troubleshooting and
  the step-by-step sandbox walkthrough moved to `docs/TROUBLESHOOTING.md`. The new docs are `docs/ARCHITECTURE.md`
  (flow, code map, trust boundaries) and `docs/SUBMISSION.md` (form text). The original spec moved to
  `docs/archive/BUILD_PROMPT.md`, and the v1-v2 milestone history and session notes to
  `docs/archive/PROGRESS_v1_v2.md`. `docs/PROGRESS.md` keeps only v3. `CLAUDE.md` points to `FIX_PLAN.md` as the
  current plan. Hosted-demo and video links stay placeholders until the human tasks are done. `LICENSE` is the
  standard MIT text, unchanged.

## Not used in v1 (sponsor tools)

- **Bryntum:** a CSS timeline is enough for a prototype.
- **Elastic:** about 20 dark-pattern examples fit in a JSON file.
- **KERNEL:** our dummy site is local, so local Playwright is simpler than a cloud browser + tunnel.
- **Postman:** the README + FastAPI's `/docs` are enough.
- **Astropods:** not needed to run or judge the prototype.
- **Channel3:** product search doesn't fit this project.

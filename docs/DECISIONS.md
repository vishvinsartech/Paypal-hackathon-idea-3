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
- **D-053 Scripted demo usage.** *(Now Penwright only: D-096.)* The demo seed writes usage events with `source: "seed"` (Priya: Framewise
  Days -2, 3, 10 and Penwright Days 2, 4; John: Lumen Days 1-9 and 12). Only days <= today count, so the
  story's numbers ("opened Penwright twice", "3 times this month", "9 of the last 10 days", "2 weeks")
  are reproducible; opening `/shop/<merchant>/app` still adds live events on top.
- **D-054 Demo seed subscriptions.** *(Superseded by D-090.)* In mock mode with `DEMO_SEED=true` (default; tests turn it off),
  first start and Reset create Priya's Framewise (signup Day -5, so it renews Day 25 and the Day 21 price
  rise lands before it) and John's Lumen monthly (Day 0, reviewed by the real pipeline: risk 15). Penwright
  is not seeded: Priya subscribes through the shop + companion in the demo. Sandbox mode seeds nothing.
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

## Story simplified to Priya + Penwright (2026-11-10)

- **D-090 One persona, one merchant.** At the user's request the demo story (spec section 2) is now Priya +
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
- **D-096 Demo seed = usage only.** `DEMO_SEED` now writes only Priya's scripted Penwright opens (Days 2 and 4),
  so "You've opened it twice" is reproducible. No subscriptions are seeded; the dashboard starts empty and Priya
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

## Not used in v1 (sponsor tools)

- **Bryntum:** a CSS timeline is enough for a prototype.
- **Elastic:** about 20 dark-pattern examples fit in a JSON file.
- **KERNEL:** our dummy site is local, so local Playwright is simpler than a cloud browser + tunnel.
- **Postman:** the README + FastAPI's `/docs` are enough.
- **Astropods:** not needed to run or judge the prototype.
- **Channel3:** product search doesn't fit this project.

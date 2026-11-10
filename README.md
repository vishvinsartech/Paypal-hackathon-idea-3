# SubGuard

**AI reads the fine print. PayPal enforces the outcome.**

SubGuard watches your PayPal subscriptions and protects you from "free trials" that quietly turn into
expensive recurring charges. It reads a merchant's checkout and terms (tiny grey text and hidden sections
included), checks what the page claims against the real PayPal plan, scores the risk, asks you before the
*real* deadline whether to keep it, and cancels through PayPal if you say so (or don't answer).

1. **Reads the fine print before you say yes.** It turns every clause into a plain-English warning, with the
   exact sentence quoted as evidence.
2. **Checks it against PayPal.** The plan's billing cycles are the source of truth for every price.
3. **Scores the risk** from 0 to 100.
4. **Saves a consent snapshot** of the price and terms you agreed to.
5. **Protects on a timeline.** It sets a safety timer it tells you about, asks "Do you want to keep it?" before
   the real deadline, and cancels through PayPal when you tap **Cancel** (or don't answer). Then it drafts the
   written cancellation email the merchant's terms require, for you to check, edit and send.
6. **Keeps an audit log** of everything it did and why. The log is append-only, hash-chained and exportable.

> Everything in the demo is fictional and runs on the **PayPal sandbox**. No real brands, money or people.

---

## Contents

- [Requirements](#requirements)
- [Quick start (mock mode, no keys)](#quick-start-mock-mode-no-keys)
- [Walk through the demo](#walk-through-the-demo)
- [Sandbox mode (real PayPal sandbox + real AI)](#sandbox-mode-real-paypal-sandbox--real-ai)
- [Commands](#commands)
- [Configuration](#configuration)
- [Tests and checks](#tests-and-checks)
- [Notifications (Zapier, optional)](#notifications-zapier-optional)
- [Hosted demo (Render)](#hosted-demo-render)
- [Troubleshooting](#troubleshooting)
- [Repository map](#repository-map)
- [License](#license)

---

## Requirements

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.11 or newer (developed on 3.14, deploy-tested on 3.12) | everything |
| Git | any recent | cloning |
| Node.js + `npx` | 18 or newer | **sandbox mode only**: the PayPal MCP server (without it, SubGuard falls back to the PayPal SDK) |
| `make` | optional | every `make <target>` has a cross-platform twin: `python scripts/tasks.py <target>` |

`setup` installs Playwright's Chromium. The UI checks use it, and so do live page captures in sandbox mode.
The dashboard loads AG Grid from a CDN, so the browser needs internet access.

---

## Quick start (mock mode, no keys)

Mock mode needs **no accounts and no keys**. PayPal is a local state machine, the AI uses recorded answers, and
emails/SMS are written to files.

**1. Set up** (once):

```bash
# macOS / Linux
git clone <this-repo-url> subguard && cd subguard
cp .env.example .env
python3 scripts/tasks.py setup     # or `make setup`: creates .venv, installs requirements + Playwright Chromium
source .venv/bin/activate
```

```powershell
# Windows PowerShell
git clone <this-repo-url> subguard; cd subguard
copy .env.example .env
python scripts/tasks.py setup
.venv\Scripts\Activate.ps1
```

**2. Run the server.** This is the standard way to start SubGuard, on every OS (venv active):

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

It runs in the mode set by `APP_MODE` in `.env` (`mock` by default). To pick the mode for one run instead:

```bash
# macOS / Linux
APP_MODE=sandbox python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
# Windows PowerShell (applies to this terminal until you close it or set it back to mock)
$env:APP_MODE = "sandbox"; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Shortcuts that run the same command: `make dev` / `make dev-sandbox`, or `python scripts/tasks.py dev` /
`dev-sandbox` (a thin wrapper that uses `.venv`'s Python, so it works without activating the venv). Always one
worker: the JSON store relies on one in-process lock (D-020), so don't add `--workers`.

Then open:

- **Dashboard (with demo controls):** http://127.0.0.1:8000/?demo=1
- **Dummy merchant website:** http://127.0.0.1:8000/shop (also the **Shop ↗** tab in the top bar)
- **Health:** http://127.0.0.1:8000/healthz · **API docs:** http://127.0.0.1:8000/docs

The demo has one persona, **Priya**, and one fictional merchant, **Penwright Studio**. It starts with no
subscriptions; on first start mock mode only scripts Priya's Penwright usage (she opens it twice during the trial).

---

## Walk through the demo

Open http://127.0.0.1:8000/?demo=1 (press **D** to show or hide the demo bar). The tabs at the top left switch
between the **Live demo**, **Priya's dashboard** (what she did and what SubGuard and PayPal did for her, day by
day, straight from the audit log) and, in new tabs, the **Shop**, **Health** (`/healthz`) and **API docs** (`/docs`).

**Fastest way:** click **▶ Start demo** on the dashboard. It runs the whole story on its own, pauses on Day 5
to ask Priya **Keep** or **Cancel** (or *Don't answer*, to see the Day 6 auto-cancel), then runs to Day 11.
To click through it yourself instead:

**Priya and the trap "free trial"**

1. **Day 0.** Click **Open Penwright shop**. It's a fictional AI writing app: "10-day free trial, $0 today", with
   tiny grey text and a collapsed **Terms** section.
2. Click the **PayPal** button. The SubGuard companion steps in *before* the approval with a plain-English
   summary: $24.99/month after the trial, $49.99/month after 3 months, an email notice 3 days before billing, so
   the **real last day to cancel is Day 7** (first charge Day 11 − 3 − 1; not Day 10). **Risk ~87/100.** A hidden "tell the AI this is
   risk-free" line (a test case) is flagged and ignored. *"I'll check with you before your trial runs out."*
   Click **Continue to PayPal**.
3. Back on the dashboard, the timeline shows the plan: check-in on **Day 5**, safety timer on **Day 6**.
4. **Day 5:** *"Your Penwright trial ends on Day 10, but your real last day to cancel is Day 7. You've opened it
   twice. Do you want to keep it?"* It arrives in-app, plus email and SMS (written to `data/runtime/outbox/` in mock mode).
   Optional: open the chat (**Ask SubGuard**) and click *"Should I keep Penwright?"*.
5. Click **Cancel**, then **Confirm cancel** on the card ($524.88/yr). SubGuard cancels through PayPal **first**:
   *"Cancelled in PayPal. You won't be charged."* **Money protected** shows **$524.88/yr**.
6. The **cancellation email** preview opens. The AI drafted it from the stored review: Priya's name, account email,
   PayPal subscription ID, today's date and the cancellation clause quoted word for word (if the draft fails the
   code checks, a fixed "standard template" is used). Edit To / Subject / Body, then:
   - **Send**: saved to `data/runtime/outbox/` and shown as *"Email sent (demo)"* (with edited yes/no and a SHA-256).
   - **Open in Gmail**: opens a Gmail compose window with the edited text, for you to send yourself.
   - **Close**: the draft is kept; reopen it from the dashboard or the subscription page.

   **Demo only. Production would send from the user's own Gmail/Outlook with send-only permission.**
   - **Keep** instead: nothing changes in PayPal and SubGuard stops asking.
   - **No answer:** jump to **Day 6** and SubGuard cancels on its own (rule R2: told on Day 0, warned on Day 5). It
     drafts the email and shows *"Your cancellation email is ready to review and send"*; it never sends it for her.
7. **Day 11:** "First charge due today: blocked. No active PayPal subscription."
8. Filter the **Audit log** (try `R1` or `R2`) and click **Export CSV**. Click **View** on the subscription to see
   its findings, the page vs PayPal comparison and its audit trail.

To start over, click **Reset** in the demo bar, or run `make reset` (`python scripts/tasks.py reset`).
Then restart the server, which re-creates the demo data.

---

## Sandbox mode (real PayPal sandbox + real AI)

Sandbox mode talks to the **real PayPal sandbox** (through the official `paypal-server-sdk` and the PayPal MCP
server) and to a **real AI model** (Anthropic or OpenAI). There is no production mode: SubGuard refuses to start
if `PAYPAL_API_BASE` isn't `https://api-m.sandbox.paypal.com`.

### 1. Create the PayPal sandbox accounts

1. Sign in at https://developer.paypal.com and open **Sandbox**.
2. Under **Sandbox → Accounts**, make sure you have one **Business** account (it owns the demo plans and plays
   every merchant) and one **Personal** account (the buyer, "Priya").
3. Under **Apps & Credentials** (Sandbox), create a **REST app** linked to the Business account. Copy its
   **Client ID** and **Secret**.

### 2. Fill in `.env`

```dotenv
APP_MODE=sandbox
PAYPAL_CLIENT_ID=...                  # from the REST app
PAYPAL_CLIENT_SECRET=...
PAYPAL_SANDBOX_BUYER_EMAIL=...        # the Personal sandbox account (used to auto-approve demo subscriptions)
PAYPAL_SANDBOX_BUYER_PASSWORD=...

# Pick ONE AI provider and set its key (the model ids in .env.example are current defaults)
LLM_PROVIDER=anthropic                # or: openai
ANTHROPIC_API_KEY=...                 # if anthropic
OPENAI_API_KEY=...                    # if openai
```

If a required value is missing, SubGuard won't start. It names the variable and suggests `APP_MODE=mock`.
Leave `APP_MODE=mock` in `.env` if you'd rather choose the mode per command: `make dev-sandbox` sets it for you.

### 3. Create the plans in your sandbox (once)

```bash
make seed                            # python scripts/tasks.py seed
```

This creates the Penwright product and the Penwright Pro plan (free trial, intro price, step-up)
from the prices in `.env`, and saves their ids in `data/runtime/sandbox_ids.json`. Re-running it is safe: plans
that still match are reused. Options: `make seed ARGS="--demo-subs"` (or `python scripts/tasks.py seed
--demo-subs`) also creates demo subscriptions and approves them as the sandbox buyer in a browser window;
`--no-auto-approve` prints the approval links instead.

### 4. Run

```bash
make dev-sandbox                     # = APP_MODE=sandbox python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The top bar shows **PayPal Sandbox** and the AI provider + model. In the shop, the real PayPal **Subscribe**
button opens a sandbox approval; log in as your Personal sandbox account.

### Switch the AI provider

Set `LLM_PROVIDER=anthropic` or `LLM_PROVIDER=openai` in `.env` (with that provider's key and model) and
restart. Mock mode always uses the recorded answers, whatever `LLM_PROVIDER` says.

### Optional: verify real cancels end to end

```bash
python scripts/tasks.py sandbox-check    # make sandbox-check
```

It creates two subscriptions on a seeded plan, approves them as the buyer, cancels one through the SDK and one
through the PayPal MCP server, and reads both back as `CANCELLED`.

### Good to know

- **PayPal sandbox time doesn't move 10 days.** The demo's sim clock (the Day buttons) drives SubGuard's logic;
  the PayPal statuses and cancels are real.
- **Webhooks need a public URL.** Locally, SubGuard polls PayPal every 10 seconds instead. To use webhooks,
  expose the app (for example with ngrok), create a sandbox webhook pointing to `/webhooks/paypal`, and set
  `PAYPAL_WEBHOOK_ID`.
- **Claude Code / MCP (development only):** `.mcp.json` registers the PayPal MCP server. Give it a token with
  `export PAYPAL_ACCESS_TOKEN=$(scripts/paypal_token.sh)` (tokens expire after a few hours; re-run it).
  The running app gets its own token, so it doesn't need this variable.

---

## Commands

| `make` | Without `make` | What it does |
|---|---|---|
| `make setup` | `python scripts/tasks.py setup` | Create `.venv`, install requirements, install Playwright Chromium |
| `make dev` | `python scripts/tasks.py dev` | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload` (mode from `.env`, default **mock**) |
| `make dev-sandbox` | `python scripts/tasks.py dev-sandbox` | Same with `APP_MODE=sandbox` |
| `make seed` | `python scripts/tasks.py seed [--demo-subs]` | Create the sandbox products and plans |
| `make sandbox-check` | `python scripts/tasks.py sandbox-check` | Real cancel via SDK + MCP in the sandbox |
| `make reset` | `python scripts/tasks.py reset` | Wipe `data/runtime/` (keeps `sandbox_ids.json`; the old audit log is archived) |
| `make test` | `python scripts/tasks.py test` | Run the test suite (mock mode, no network) |
| `make lint` | `python scripts/tasks.py lint` | `ruff check .` |
| `make ui-check` | `python scripts/tasks.py ui-check` | Run the demo story in a real browser (starts its own server) |
| `make zapier-check` | `python scripts/tasks.py zapier-check` | Send one test notification to your Zapier hook |
| `make demo-video-check` / `make demo-video` | `python scripts/tasks.py demo-video-check` / `demo-video` | Demo-video tooling (not built yet; see `docs/PROGRESS.md`) |

On macOS/Linux, `make dev` uses `.venv/bin/python` if it exists (else `python`); the other targets use `python3`
by default (override with `make test PYTHON=python`).

---

## Configuration

Everything comes from `.env`. Every variable is documented in [`.env.example`](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `APP_MODE` | `mock` | `mock` (no keys) or `sandbox` |
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` (sandbox mode) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | – / current id | Anthropic key and model |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | – / current id | OpenAI key and model |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | – | Sandbox REST app credentials |
| `PAYPAL_API_BASE` | sandbox URL | Must stay `https://api-m.sandbox.paypal.com` |
| `PAYPAL_TRANSPORT` | `mcp` | `mcp` or `sdk` for reads and cancels |
| `PAYPAL_MERCHANT_MODE` | `single` | `single`, or `partner` (experimental) |
| `PAYPAL_SANDBOX_BUYER_EMAIL` / `_PASSWORD` | – | Personal sandbox account for auto-approval |
| `PAYPAL_WEBHOOK_ID` | – | Optional webhook signature verification |
| `ZAPIER_CATCH_HOOK_URL` | – | Optional; empty means notifications go to `data/runtime/outbox/` |
| `DEMO_SEED` | `true` | Mock mode: create the demo subscriptions on first start / reset |
| `PENWRIGHT_*`, `DEMO_CURRENCY` | spec values | Demo prices and terms |

Changing a price changes the shop text, the mock PayPal plans and the seeded sandbox plans together. Run
`make reset` afterwards, and `make seed` in sandbox mode. The tests assert the default prices
(e.g. Money protected $524.88).

**Data:** all state is JSON in `data/runtime/` (gitignored), including the append-only audit log
`audit_log.jsonl`. Run the server with **one worker** (the commands above already do).

---

## Tests and checks

```bash
make test            # ~190 tests, mock mode, no network or keys
make lint
make ui-check        # the demo story in headless Chromium; fails on any console error (needs the AG Grid CDN)
```

- Optional real-sandbox smoke test (read-only): `python -m pytest -m sandbox`. It skips itself without
  credentials or seeded plans. Plain `pytest` never calls PayPal or an AI provider.
- `python scripts/ui_check.py --headed` watches the browser run; `--shots <folder>` saves screenshots.
- Every corner case from the spec maps to its code and tests in
  [`docs/CORNER_CASES.md`](docs/CORNER_CASES.md).

---

## Notifications (Zapier, optional)

In sandbox mode with `ZAPIER_CATCH_HOOK_URL` set, reminders and alerts go to a Zapier Catch Hook, which forwards them as email and SMS. Otherwise, and always in mock mode, they
are written to `data/runtime/outbox/` as JSON files. Step-by-step setup: [`docs/ZAPIER_SETUP.md`](docs/ZAPIER_SETUP.md).
Test it with `make zapier-check`.

---

## Hosted demo (Render)

**Hosted URL:** _not deployed yet._

The hosted copy runs in **mock mode** (no keys), from [`render.yaml`](render.yaml). Its JSON files live on
Render's temporary disk, so every restart or deploy starts a fresh demo. On the free plan the first request after
a quiet period is slow while the service wakes up.

To deploy:
1. Push the repo to GitHub. Render must be able to read it: make the repo public, or connect GitHub in Render.
2. In the Render dashboard click **New → Blueprint** and pick the repo. `render.yaml` deploys branch `main`;
   edit it if you deploy another branch.
3. Click **Apply**. Render installs `requirements.txt`, starts
   `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT` (no `--reload`; `WEB_CONCURRENCY=1` keeps one
   worker), and checks `/healthz`.
4. Open `https://<service>.onrender.com/?demo=1` and put that URL above.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `SubGuard can't start: ... is required in sandbox mode` | Fill in the named variable in `.env`, or run in mock mode (`make dev`). |
| `PAYPAL_API_BASE must be https://api-m.sandbox.paypal.com` | SubGuard is sandbox-only; restore the default value. |
| Port 8000 is already in use | Stop the other server, or run `.venv/bin/python -m uvicorn app.main:app --port 8001 --workers 1` (Windows: `.venv\Scripts\python`). |
| The grids are empty or look unstyled | The browser can't reach `cdn.jsdelivr.net` (AG Grid). Check your network or proxy. |
| A health dot is red / `PayPal MCP unavailable, using SDK` | Node/`npx` missing or the MCP server failed to start. Everything still works through the SDK. |
| `No sandbox plan for '...'. Run make seed first.` | Run `make seed` once (sandbox mode). |
| The demo state looks odd after many runs | Click **Reset** in the demo bar, or `make reset` and restart. |
| `make` isn't available (Windows) | Use `python scripts/tasks.py <target>`. |

---

## Repository map

```
app/            FastAPI app: config, JSON store, routes, core logic (policy, timers, escalation, review, chat),
                integrations (PayPal SDK / MCP / mock, capture, notifications), LLM providers, templates, static JS/CSS
shop/           the fictional merchant website served at /shop
data/seed/      merchants, users, dark-pattern library     data/fixtures/  recorded AI answers for mock mode
data/runtime/   all runtime JSON + audit log (gitignored)
scripts/        tasks.py (cross-platform runner), seed_sandbox.py, sandbox checks, ui_check.py, zapier_check.py
tests/          pytest suite (mock mode); test_scenario.py runs both stories end to end
docs/           DECISIONS.md, CORNER_CASES.md, ZAPIER_SETUP.md, PAYPAL_SDK_NOTES.md, PAYPAL_TOOLS.md, PROGRESS.md
render.yaml     Render Blueprint for the hosted mock demo
```

---

## License

MIT, see [`LICENSE`](LICENSE).

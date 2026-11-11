# Troubleshooting and sandbox details

Moved out of the README to keep it short. Every `make <target>` also runs as `python scripts/tasks.py <target>`.

## Common problems

| Problem | Fix |
|---|---|
| `SubGuard can't start: ... is required in sandbox mode` | Fill in the named variable in `.env`, or run in mock mode (`make dev`). |
| `PAYPAL_API_BASE must be https://api-m.sandbox.paypal.com` | SubGuard is sandbox-only; restore the default value. |
| `No sandbox plan for '...'. Run make seed first.` | Run `make seed` once (sandbox mode). |
| Review says "basic check (AI unavailable)"; audit log shows `OpenAI API error 404: Your organization must be verified` | Verify the organization at platform.openai.com (Settings -> General), or set `OPENAI_MODEL` to a model your key can use, then restart. |
| A health dot is red / `PayPal MCP unavailable, using SDK` | Node/`npx` is missing or the MCP server failed to start. Everything still works through the SDK. |
| Port 8000 is already in use | Stop the other server, or run `python -m uvicorn app.main:app --port 8001` from the venv. |
| The demo state looks odd after many runs | Press **Reset** in the presenter bar (`?demo=1`, or press D), or `make reset` and restart. |
| `make` isn't available (Windows) | Use `python scripts/tasks.py <target>`. |
| Pop-ups blocked when Start demo opens the shop | Allow pop-ups for 127.0.0.1. |
| PayPal's window closed or "Cancel and return" chosen | Nothing was set up. Click Subscribe again. |
| Hosted demo is slow on the first request | Render's free plan sleeps when idle; the first request wakes it. |

AG Grid and AG Charts are vendored in `app/static/vendor/`, so the UI needs no CDN.

## Sandbox mode, step by step

### 1. PayPal sandbox accounts

1. Sign in at https://developer.paypal.com and open **Sandbox**.
2. Under **Sandbox -> Accounts**, have one **Business** account (owns the demo plans, plays both merchants) and one
   **Personal** account (the buyer, Priya).
3. Under **Apps & Credentials** (Sandbox), create a **REST app** linked to the Business account. Copy its
   **Client ID** and **Secret**.

### 2. `.env`

```dotenv
APP_MODE=sandbox
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_SANDBOX_BUYER_EMAIL=...        # the Personal sandbox account
PAYPAL_SANDBOX_BUYER_PASSWORD=...
LLM_PROVIDER=anthropic                # or: openai
ANTHROPIC_API_KEY=...                 # if anthropic
OPENAI_API_KEY=...                    # if openai
```

A missing value stops startup with the variable's name and a hint to use `APP_MODE=mock`.

### 3. Seed the plans (once)

`make seed` creates the Penwright and Quillnote products and plans from the `.env` prices and saves their ids in
`data/runtime/sandbox_ids.json`. Re-running is safe: matching plans are reused. `make seed ARGS="--demo-subs"` also
creates a demo subscription and approves it as the buyer in a browser; `--no-auto-approve` prints the links instead.

### 4. Run and walk through

`make dev-sandbox`, then open http://127.0.0.1:8000/?demo=1 and press **Start demo**:

1. The shop opens in a new window and plays Priya: it opens the Terms and clicks PayPal. The companion's review
   (real AI) stays on screen for a few seconds, then continues.
2. Click **Subscribe with PayPal**. PayPal's own approval window opens, logged in as the Personal sandbox account.
   Click **Continue**, then **Agree & Subscribe**.
3. The shop shows "You're subscribed", and the demo carries on: safety timer, the days, the Day 5 Keep / Cancel
   check-in, then Day 11.

After a cancel, the card shows **CANCELLED** read from PayPal, plus a link to the buyer's Automatic payments page
(`PAYPAL_AUTOPAY_URL`).

### Optional checks

- `make sandbox-ui-check` (add `ARGS="--headed"` to watch): starts a sandbox server on throwaway data, approves in
  PayPal's real window as the buyer, checks ACTIVE, cancels, checks CANCELLED, then cleans up anything still
  ACTIVE. Without an LLM key it runs PayPal-only with the basic review.
- `make sandbox-check`: creates two subscriptions, approves them, cancels one through the SDK and one through the
  PayPal MCP server, and reads both back as CANCELLED.
- `python -m pytest -m sandbox`: read-only smoke test; skips itself without credentials or seeded plans.

## Good to know

- **PayPal sandbox time doesn't move.** The presenter bar's day buttons move SubGuard's sim clock (Day 5 check-in,
  Day 6 timer, Day 11 charge). The PayPal statuses and cancels are real; no real charge happens on "Day 11".
- **Webhooks need a public URL.** Locally SubGuard polls PayPal every 10 seconds. To use webhooks, expose the app
  (for example with ngrok), create a sandbox webhook to `/webhooks/paypal`, and set `PAYPAL_WEBHOOK_ID`.
- **Claude Code / MCP (development only).** `.mcp.json` starts the PayPal MCP server through
  `scripts/mcp_paypal.mjs`, which reads `.env`, gets a fresh sandbox token and runs `npx -y @paypal/mcp --tools=all`.
  If a token expires, reconnect with `/mcp`. The running app gets its own token.
- **Changing prices.** Prices and terms are `.env` variables (`PENWRIGHT_*`, `QUILLNOTE_*`). A change updates the
  shop text, the mock plans and the seeded sandbox plans together. Run `make reset`, and `make seed` in sandbox
  mode. The tests assert the default prices.
- **Logs.** `LOG_ALL_REQUESTS=true` prints every request; by default background polling is hidden.
- **Zapier.** Step-by-step setup: [`ZAPIER_SETUP.md`](ZAPIER_SETUP.md). Test with `make zapier-check`.

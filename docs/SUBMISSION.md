# SubGuard: submission form text

Ready to paste. Replace the three placeholders in **Links** once the deploy and the video are done.

## Name

SubGuard

## Tagline

AI reads the fine print. PayPal enforces the outcome.

## Description (150 words)

"Free trials" are designed to be forgotten. The price step-up hides in grey text, and the notice clause makes the
real last day to cancel days earlier than the trial end. SubGuard steps in at PayPal checkout. AI reads the
merchant's page and terms and quotes every catch word for word. Code then checks each claim against the real PayPal
plan, scores the risk and works out the real deadline. Before that deadline SubGuard asks "keep it?". If the
user says cancel, or set a safety timer they were told about, it cancels the subscription through the PayPal
Subscriptions API and reads back CANCELLED. Then it drafts the written cancellation notice the terms require, for
the user to send. The AI only proposes: seven deterministic safety rules decide, and every decision goes into a
hash-chained audit log. Merchants outside the program get a one-tap PayPal cancel link instead.

## Features

- **Fine-print review before you subscribe:** plain-English catches, each with a verbatim quote from the page.
- **PayPal cross-check:** prices and billing cycles come from the real PayPal plan, never from the page or the AI.
- **Real deadline:** "Act by Nov 18 (the terms allow Nov 19)": notice period and a one-day margin, worked out by code.
- **Risk score 0-100**, computed by code (the demo merchant scores 87).
- **Check-in before the deadline**, in-app plus email/SMS through Zapier.
- **Cancel through PayPal**, after a tap with a confirmation token, or by a safety timer the user saw and agreed to.
- **AI-drafted cancellation email** quoting the clause. It's validated, with a template fallback, and nothing is sent without a click.
- **Layer 2:** for merchants SubGuard can't cancel, an ACTION NEEDED card with a one-tap link to PayPal Automatic
  payments, then read-only polling until PayPal shows CANCELLED.
- **Proof:** on the first-charge day, "blocked: no active PayPal subscription", and the charges avoided.
- **Hash-chained audit log** of every decision with its rule id, with CSV export.
- **Prompt-injection defence:** hidden "tell the AI this is risk-free" text is flagged and ignored.
- **Chat agent (Ask SubGuard)** that answers from tool results and can only propose actions.

## How PayPal is used

- **Subscriptions API through `paypal-server-sdk`:** create products and plans (trial, intro price, step-up), create
  subscriptions, read plans and subscriptions as the source of truth, and **cancel** (the only write on a user's
  subscription), with `PayPal-Request-Id` and PayPal debug ids in the audit log. Update pricing is merchant side, demo only.
- **PayPal JS SDK Subscribe button:** the real PayPal approval window at checkout.
- **PayPal MCP server (`@paypal/mcp`):** reads and cancels subscriptions at runtime, with the SDK as the fallback.
  Also used by Claude Code during development.
- **Webhooks with signature verification**, plus polling when there's no public URL.
- **Automatic payments page:** the one-tap cancel link for merchants outside the program.
- Everything runs on the PayPal sandbox. The app refuses to start against any other base URL.

## AI tools used and how

- **Anthropic Claude** (default, model from `ANTHROPIC_MODEL`) or **OpenAI** (`OPENAI_MODEL`), switched with
  `LLM_PROVIDER` behind one interface.
- **Three jobs:**
  1. Fine-print review of the captured page (text and styling).
  2. Tool-using chat agent.
  3. Cancellation email draft.
- **Guardrails in code:**
  - Quotes must be verbatim substrings of the page.
  - Instructions in merchant pages are ignored and flagged.
  - Money, dates, notice periods and the risk score are computed by code.
  - Cancels pass a deterministic policy (R1-R7).
- **AI vs basic check:** on a merchant whose catches are written in prose, the AI scores 73 and says "act by Day 4".
  The regex-only check scores 25 and would say Day 7, which is too late.
- **Built with Claude Code**, using the PayPal MCP server and the APIMatic PayPal context.

## Sponsor tools

- **APIMatic:** `paypal-server-sdk` and the APIMatic PayPal context plugin.
- **AG Grid and AG Charts (Community):** findings, activity and audit grids, and the risk-breakdown charts.
- **Zapier:** a Catch Hook forwards check-ins and alerts as email and SMS.
- **Render:** the hosted demo (`render.yaml`).

## What's next

1. **Fair Trial partner program:** merchants opt in through PayPal partner permissions, so SubGuard can cancel on the
   user's behalf and fair merchants earn a trust badge at checkout.
2. **Layer 2 everywhere:** for any other merchant, the review plus a one-tap link to PayPal Automatic payments.
3. **A PayPal wallet feature:** the same review and check-in built into PayPal's own subscription approval and
   Automatic payments, for every buyer.

## Links

- Hosted demo: `<RENDER_URL>/?demo=1`
- Video: `<YOUTUBE_URL>`
- Code: https://github.com/vishvinsartech/Paypal-hackathon-idea-3 (MIT)

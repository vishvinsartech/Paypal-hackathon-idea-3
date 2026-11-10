# Zapier setup (optional; sandbox mode only)

SubGuard reaches people **outside the app** through one Zapier Catch Hook: the Day 5 "keep it or cancel?"
check-in, and the written cancellation notice to the merchant. Without a hook (and always in mock
mode) the same messages are written to `data/runtime/outbox/` as JSON files, so the demo works with no Zapier
account.

## What SubGuard sends

One `POST` per message to `ZAPIER_CATCH_HOOK_URL`, as JSON:

```json
{
  "type": "user_alert",                       // or "merchant_cancellation"
  "to": {"email": "usera@subguard-demo.example", "phone": "+15550100001"},
  "subject": "Penwright: I'll cancel it tomorrow",
  "body": "Your real deadline is in 2 days. ...",
  "cta_url": "http://127.0.0.1:8000/?user=usera",
  "idempotency_key": "timer-warn:tm-1a2b3c:5",
  "channels": ["email", "sms"]                // what the user's settings allow
}
```

- Any **2xx** reply counts as **accepted**. Otherwise SubGuard retries 3 times with backoff (0.5 s, 1 s, 2 s),
  then marks the channel **failed**. Rule R2 still lets a safety timer fire if the in-app alert was shown
  ("in-app only if Zapier is down", logged as `zapier_down_in_app_only`).
- "Accepted" means Zapier received the message. Whether the email or SMS was then delivered is shown in Zap
  History, not in SubGuard.
- The demo people and merchants are fictional (`*.example` addresses, `+1555...` numbers). Send everything to
  **your own** inbox and phone in the Zap, and keep the original `to` values in the message text.

## Build the Zap (about 10 minutes)

1. Go to zapier.com, click **Create → Zaps**.
2. **Trigger:** search **Webhooks by Zapier** (a premium Zapier app) → event **Catch Hook** →
   **Continue**. Leave "Pick off a child key" empty → **Continue**.
3. Copy the webhook URL (`https://hooks.zapier.com/hooks/catch/<id>/<key>/`) and put it in `.env`:
   `ZAPIER_CATCH_HOOK_URL=https://hooks.zapier.com/hooks/catch/...`
4. Send a sample so Zapier learns the fields:
   `python scripts/tasks.py zapier-check` (it should print `Delivery: {'email': 'accepted'}`).
   Back in Zapier, click **Test trigger** and pick the request that shows `type: user_alert`.
5. **Action 1, the email:** add **Email by Zapier → Send Outbound Email**.
   - To: *your own email*
   - Subject: `[SubGuard] ` + **Subject**
   - Body: **Body**, a blank line, `Open SubGuard: ` + **Cta Url**, a blank line,
     `(Demo recipient: ` + **To Email** + `, type: ` + **Type** + `)`
   - Reply-to: leave empty. Test the step, then check your inbox.
6. **Action 2, SMS (optional):** add **Filter by Zapier**: continue only if **Channels** *(Text) Contains*
   `sms` **and** **Type** *(Text) Exactly matches* `user_alert`. Then add **SMS by Zapier → Send SMS**:
   To = *your verified phone number*, Message = **Subject** + `: ` + **Body** (Zapier trims long messages).
   Run `python scripts/zapier_check.py --sms` to test it.
7. **Merchant notices** (`type: merchant_cancellation`) go through the same email step. To see the written
   cancellation notice in your inbox, run `python scripts/zapier_check.py --merchant-notice`.
8. Name the Zap **SubGuard notifications** and click **Publish**.

## Use it

- `ZAPIER_CATCH_HOOK_URL` is only used in **sandbox mode** (`make dev-sandbox`). `/healthz` and the health dots
  show `notify: sandbox (zapier)`; without the hook they show `mock (outbox)`, and startup logs a warning.
- Every send is in the audit log as `alert_sent`, with each channel's result
  (`in_app:shown,email:accepted,sms:accepted`).
- The hosted Render demo runs in mock mode and never calls Zapier.

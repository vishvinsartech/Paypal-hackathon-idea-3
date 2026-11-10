# SubGuard

**AI reads the fine print. PayPal enforces the outcome.**

SubGuard reads subscription fine print, checks it against the real PayPal plan, scores the risk, and cancels
trials and price rises through PayPal before the real deadline. (The full README comes in milestone 10.)

## Quick start (mock mode, no keys)

```bash
cp .env.example .env
make setup        # Windows without make: python scripts/tasks.py setup
make dev          # python scripts/tasks.py dev
```

Open http://127.0.0.1:8000/?demo=1. The dummy merchant website is at http://127.0.0.1:8000/shop.

## Hosted demo (Render)

**Hosted URL:** _not deployed yet_ (see `docs/PROGRESS.md`, milestone 8).

The hosted copy runs in **mock mode** (no keys). Its JSON files live on Render's temporary disk, so every restart or
deploy starts a fresh demo. On the free plan the first request after a quiet period takes a little while (the
service wakes up).

Deploy it yourself from `render.yaml`:
1. Push this repo to GitHub. Render needs to read it: make the repo public, or connect GitHub in Render.
2. In the Render dashboard click **New → Blueprint**, pick the repo, and keep the branch in `render.yaml`
   (`main`) or change it to the branch you pushed.
3. Click **Apply**. Render runs `pip install -r requirements.txt`, then
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`, and checks `/healthz`.
4. Open `https://<service>.onrender.com/?demo=1`, and paste that URL above.

## Notifications (Zapier, optional)

In sandbox mode with `ZAPIER_CATCH_HOOK_URL` set, reminders, alerts and the merchant's written cancellation notice
go to a Zapier Catch Hook (email + SMS). Otherwise, and always in mock mode, they're written to
`data/runtime/outbox/`. Setup: `docs/ZAPIER_SETUP.md`; test it with `python scripts/tasks.py zapier-check`.

## License

MIT, see `LICENSE`.

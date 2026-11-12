# Phase 7 plan: sign-in, intro page, dashboard polish, mobile pass, Render deploy, video

Branch: `phase7-webapp` (from `prototype-v3` at `9f30e0d`, "v3: Phase 6 UI baseline"). When everything is done, merge it into `main` and deploy `main` on Render.

## Context

The UI work is finished. What's left for the hackathon is a "real product" front door:

- A signed-out visitor sees a short intro page and a sign-in page.
- Priya signs in with her email and password and lands on her dashboard. The dashboard gets a Sign out button and a few clearly labelled demo-only controls.
- Shop subscriptions keep showing up on her dashboard.
- The phone layout is checked on every new page.
- Then we deploy to Render and record the video.

There is no sign-up and no native app. "Mobile app" means the phone layout.

### What the code does today

- **No auth.** The user comes from a `?user=` query parameter that defaults to `"priya"` on every route (`user_page.py:42`, `pages.py:_base`, `shop/routes.py`, `subscriptions.py`). R5 ownership filters (`owner_id == user`) already scope the data.
- **No intro page.** `_landing.html` (hero, "Meet Priya", how it works) renders only inside `/?demo=1`. Its context comes from `landing_view(settings)` in `landing.py`.
- **Dashboard.** `/` is `home.html` + `base.html`: a sidebar (Overview / Subscriptions / Activity / Emails / Analytics / Settings), an avatar menu, and a bottom tab bar at 640px or narrower (`dashboard.css:166`). It has no logout, because there are no sessions.
- **Shop to dashboard already works.** `checkout.js` calls `/api/checkout/create`, then mock-approve, then `/api/subscriptions/register` (which calls `register_active` in `app/core/signup.py`). `home.js` re-fetches `/` every 4 seconds, so the new subscription appears.
- **Render.** `render.yaml` exists (free plan, `prototype-v3`, mock mode, 1 worker), and `tests/test_deploy.py` pins it exactly. The disk is wiped on restart.
- **No `itsdangerous`** in `requirements.txt`, so Starlette's `SessionMiddleware` would add a dependency. Use a small HMAC cookie from the standard library instead.

### Decisions already made

- Mobile means the phone layout.
- The shops are public. The Live demo (`/?demo=1`) needs sign-in.
- The password is private and lives only in an env var.

---

## Step 0: Baseline commit

**Done.** `9f30e0d` "v3: Phase 6 UI baseline" was committed and pushed after test, lint and ui-check all passed.

Remaining: add a "Phase 7: Sign-in, intro, deploy" section with checklist rows (Steps V and 1–8) to `docs/FIX_PLAN.md`, following the existing workflow, plus a Phase 7 entry in `docs/PROGRESS.md`.

---

## Step V: Video tooling v2

Upgrade `demo-video/` from a raw screen recording with captions to a presented product video (based on a reference video):

- a word-by-word headline synced to the voice-over
- the app shown inside a browser frame, with the real URL and a mode pill
- motion-graphic slides for the problem and "how it works"
- chapter progress bar, yellow highlights, zooms, PayPal proof scene, end card
- a fast `demo-video-preview` task
- every task runs on Windows through `python scripts/tasks.py`

The full spec and the 13-scene storyboard are in the Task 3 prompt. Scene `05_signin` stays `pending` until Step 6. Nothing is recorded in this step.

---

## Step 1: Auth core

New `app/auth.py`, kept under 300 lines.

### Settings (`config.py`)

| Variable | Rule |
|---|---|
| `DEMO_PASSWORD` | Secret, no default. |
| `SESSION_SECRET` | If empty in mock mode, use a random per-process value (sessions then end on restart). |
| `SESSION_HOURS` | Default 8. |

### Missing values

- **Sandbox mode with either secret missing:** startup error naming the variable, using the same pattern as `validate_settings`.
- **Mock mode without `DEMO_PASSWORD`:** the sign-in page says "Sign-in is off: set DEMO_PASSWORD in .env". It does not crash, so the dev server still starts on a fresh clone.
- Document both variables in `.env.example`.

### Credentials

- The email comes from `users.json`: `priya@subguard-demo.example`, already seeded.
- Compare the email case-insensitively and the password with `hmac.compare_digest`.

### Cookie `sg_session`

- Value: base64 of `user_id|expiry` plus an HMAC-SHA256 signature.
- Flags: HttpOnly and SameSite=Lax, plus Secure when the request is https.
- Nothing is stored on the server, so sessions survive Render's disk wipe as long as `SESSION_SECRET` stays the same.

### Routes (new `app/routes/auth.py`)

- `GET /login?next=`
- `POST /login` (form). Wrong details re-render with the generic "Email or password is wrong".
- `POST /logout` clears the cookie and redirects to `/`.
- `next` must be a local path; anything else falls back to `/`.
- **After sign-in, always land on the dashboard `/`** (`safe_after_login` in `app/auth.py`). The only exception is a
  `/shop` page (e.g. `/shop/penwright`, for Step 4's "Sign in to subscribe"), which is returned to. Any other `next`,
  including `/?demo=1`, goes to `/`; the Live demo is opened from the Presenter menu after sign-in.
- **Rate limit:** 5 failed sign-ins per minute per IP, using a simple in-memory counter.
- **Audit:** log `signed_in`, `sign_in_failed` and `signed_out` (actor user, decision allowed or blocked). Mask the email as the rules require, and never log the password.

### Access middleware (`app/auth.py`, registered in `create_app`)

**Public:**
- `/` (shows the intro when signed out)
- `/login`, `/logout`, `/healthz`
- `/static/*`, `/shop/static/*`, `/shop*` pages
- `/api/review/preflight` (the shop companion's read-only check)
- `/webhooks/paypal` and `/demo/paypal-autopay`

**Needs a session:** `/?demo=1`, `/subscriptions/*`, and all other `/api/*`, including checkout and register.

**Behaviour:**
- Signed-out HTML requests get a 303 redirect to `/login?next=…`.
- Signed-out API requests get a 401 JSON error.
- The signed-in user is stored on `request.state.user_id`. Routes keep their `user` parameter, so their signatures and the R5 filters don't change.
- The middleware returns 403 for any `?user=` that differs from the session user. Record this choice in DECISIONS: it's the smallest change, and R5 stays the data guard.

---

## Step 2: Intro page at / when signed out

`user_page.py` `home()`: with no session, render a new `intro.html` instead of the dashboard. Signed in, `/` stays her dashboard, so the URLs in the tests, the video and CLAUDE.md still hold.

### Intro content

Keep it short, and reuse the `landing_view` numbers so no price is hardcoded.

- **What SubGuard is:** one line, plus the tagline "AI reads the fine print. PayPal enforces the outcome."
- **How it works with PayPal, in 3 steps:**
  1. You subscribe with PayPal.
  2. SubGuard checks the terms against the real PayPal plan.
  3. It cancels through PayPal before the deadline, only with your OK or a safety timer you saw.
- **What the AI does:** it reads the fine print, finds traps (short notice, step-up prices) and quotes them word for word. Code, not the AI, makes every decision.
- **Buttons:** "Sign in" (primary) and "Browse the demo shops" (to `/shop`).
- **Footer:** the existing fictional-merchant note.

Move the shared hero and steps markup into partials, so `_landing.html` (Live demo) and `intro.html` don't repeat each other.

### Sign-in page

New `login.html`: email and password fields, an error line, a "Back" link, and a "Demo account: Priya" hint with no password shown. No sign-up link.

---

## Step 3: Dashboard additions

These apply when signed in.

### Real features

- **Avatar menu** (`base.html:51-61`): "Signed in as Priya · priya@…", then Profile, Settings, Help, and a Sign out button (a POST form). On phones the avatar menu already holds Emails and Settings, so Sign out is reachable there.
- **Signed-out top bar:** brand, "Demo shops" and "Sign in". The Presenter menu (Live demo) shows only when signed in.
- **Settings → "Connected accounts" card:** PayPal shows Connected, with the real mode from `/healthz` (Demo data or PayPal Sandbox). The email and SMS alerts row shows the Zapier state (connected or mocked).
- **Settings → "Download my activity":** links to the existing audit CSV endpoint.
- **"Last signed in"** line in the sidebar user chip, taken from the latest `signed_in` audit entry.

### Demo-only controls

All of these use one `data-soon` attribute. One handler in `user-nav.js` shows the toast "Not part of this demo". Nothing claims an action happened (R7).

- "+ Add a subscription" on the Subscriptions panel (hint: "SubGuard adds subscriptions you start with PayPal").
- Profile: edit name or photo.
- "Change password" and "Turn on two-step sign-in" in Settings → Security.
- "Delete account": disabled, labelled "Demo account".
- Help center and Privacy links in the footer.

---

## Step 4: Shop and session

- The shop pages stay public.
- **Signed out:** the merchant page's Subscribe button becomes "Sign in to subscribe with SubGuard", linking to `/login?next=/shop/penwright`.
- **Signed in:** a small "Signed in as Priya" chip shows.
- `shop/static/checkout.js` (and `checkout_sandbox.js`) stop reading `?user=` from the URL. The server puts the session user on `<body data-user>`.
- After checkout, "Open SubGuard ↗" goes to `/`. Her dashboard (same browser, same cookie) shows the new subscription through the existing 4-second refresh. No new reflection logic is needed.

---

## Step 5: Mobile layout pass

- Check the intro, sign-in, dashboard, shop and Live demo at 390px for:
  - horizontal scroll
  - input font of at least 16px (to stop iOS zoom)
  - a tap target of at least 44px for Sign in and Sign out
- Add 390px screenshots of `/` (signed out), `/login` and `/` (signed in) to `scripts/ui_check.py` and the shots.

---

## Step 6: Tests and tooling for the sign-in wall

### Fixtures

`tests/conftest.py`: `client` and `demo_client` set `demo_password` and sign in by default. Add an `anon_client`.

### New `tests/test_auth.py`

- Login works; a wrong password fails; the rate limit kicks in.
- A tampered, expired or wrong-signature cookie is rejected.
- An open redirect through `next` is blocked.
- Signed out: `/` shows the intro; `/?demo=1`, `/api/*` and `/subscriptions/x` redirect or return 401.
- A different `?user=` returns 403.
- Logout clears the cookie.
- The audit entries exist, and the password never appears in the audit log.
- The shop stays public, and checkout returns 401 when signed out.

### Tooling

- `scripts/ui_check.py`, `demo-video/record_demo.py` (both its httpx client and its Playwright context), `record_stage.py` and `check_scenes.py` sign in first with `DEMO_PASSWORD` from `.env`.
- `scenes.json`: fill in the opening beat `05_signin` (intro page, then sign in as Priya, then the dashboard). The password field is typed but masked. Update `VIDEO_SCRIPT.md`.

---

## Step 7: Render deploy

### `render.yaml`

Update `tests/test_deploy.py` to match.

- `SESSION_SECRET`: `generateValue: true`
- `DEMO_PASSWORD`: `sync: false`
- Deploy branch: `main`
- Add `--proxy-headers --forwarded-allow-ips='*'` to uvicorn, so `request.base_url` is https and the cookie gets Secure.

### Fixes for a non-localhost host

- `main.py:110`: fix the startup log, which ignores `$PORT`.
- `app/routes/demo.py:24`: the capture base is hardcoded to `127.0.0.1:8000`; use the request base instead.
- `sandbox_buyer.py` uses localhost return URLs and a server-side Playwright window. It can't run on Render, so it stays local-only and the hosted sandbox uses the JS SDK path. Record this in DECISIONS.

### Deploy

1. Merge `phase7-webapp` into `main`.
2. Connect the repo on Render (Blueprint) and set the secrets. Mock mode is the default; sandbox is optional.
3. Smoke test the live URL: `/healthz` → intro → sign in → shop subscribe → dashboard shows it → Live demo → sign out. Check at phone width too.
4. Note the known free-plan limits in the README: about 50 seconds to wake after 15 minutes idle, and data resets on restart.
5. Put the URL in `README.md` and `docs/SUBMISSION.md`. The hosted link becomes `/`, with the sign-in hint pointing to the submission text.

---

## Step 8: Demo video

1. Run `demo-video-check` against the Render URL or local.
2. Run `demo-video-preview`.
3. Run `demo-video` (voiceover → record app → record stage → build; ffmpeg is installed locally).
4. Upload the video.

Recording locally in sandbox mode shows the real PayPal proof scene. Recording on Render (mock mode) skips it.

---

## Docs per step

`docs/DECISIONS.md`, from D-178 onward:

- Cookie auth with no server sessions.
- Public vs. protected routes.
- `/` switches between intro and dashboard.
- Password from env only.
- Demo-only controls use `data-soon`.
- Sandbox buyer window is local-only.

Also:

- `docs/ARCHITECTURE.md`: an auth section.
- `CLAUDE.md`: commands and URLs (sign-in).
- `docs/PROGRESS.md` and the FIX_PLAN checklist ticked with the hash after each commit (`v3: Phase 7 …`).

## Critical files

**New:** `app/auth.py`, `app/routes/auth.py`, `app/templates/intro.html`, `app/templates/login.html`, `app/static/auth.css`, `tests/test_auth.py`, `demo-video/stage/*`, `demo-video/record_stage.py`

**Modified:** `app/config.py`, `app/main.py`, `app/routes/user_page.py`, `app/templates/base.html`, `app/templates/home.html`, `app/static/user-nav.js`, `shop/routes.py`, `shop/static/checkout*.js`, `app/routes/demo.py`, `render.yaml`, `.env.example`, `tests/conftest.py`, `tests/test_deploy.py`, `scripts/ui_check.py`, `demo-video/record_demo.py`, `demo-video/scenes.json`, `demo-video/check_scenes.py`, `demo-video/make_voiceover.py`, `demo-video/build_video.py`

## Verification

1. `python scripts/tasks.py test` (all green, including the new `test_auth.py`), then `lint`, then `ui-check` (desktop plus 390px shots of the intro, login and dashboard).
2. Manual check in mock mode at `http://127.0.0.1:8000/`:
   - Signed out, `/` shows the intro.
   - `/?demo=1` sends you to sign in.
   - A wrong password fails; the right one shows the dashboard.
   - `/shop/penwright` → subscribe → "Open SubGuard" → the card appears within about 4 seconds.
   - Sign out from the avatar menu works.
   - Repeat in the browser's phone emulation.
   - `GET /api/audit-log/verify` stays OK, and the audit log has the sign-in events with a masked email and no password.
3. After deploying: the same manual check on the Render URL, then `demo-video-check --base-url <render-url>`.
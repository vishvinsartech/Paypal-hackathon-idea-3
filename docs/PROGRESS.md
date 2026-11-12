# SubGuard build progress

v3 work follows `docs/FIX_PLAN.md` (phases 0-6). Tick each phase only after its checks pass and it is committed.
The v1-v2 milestone history (from the original spec, now `docs/archive/BUILD_PROMPT.md`) is in
`docs/archive/PROGRESS_v1_v2.md`.

## v3 (docs/FIX_PLAN.md), branch `prototype-v3`

- [x] **Phase 0. Baseline** (2026-11-11). `make test`: **286 passed**, 2 deselected (sandbox), 127 s.
  `make lint`: clean. `make ui-check`: passed (story + Start demo with all three answers, no console errors).
  Added `scripts/shots.py` (`make shots ARGS="--phase p1"`): 25 screenshots per viewport (1440×900, 390×844) in
  `docs/img/v3/<phase>/`. The baseline set `p0/` shows B1 (companion opens scrolled down), B4 (steps never tick by
  hand), B6 (floating chat button over the timeline) and B7 (axis to Day 31, "from Day 101").

- [x] **Phase 1. Correctness bugs and story logic** (2026-11-11, commits `a1ff74b`..`b4396cd`). Done: persona
  Priya, B1-B8, B10, B11, D6, D7, D8, D10, Fair Trial badge (DECISIONS D-130..D-141). Deferred as FIX_PLAN says:
  B9 (Phase 3) and B12 (Phase 4). `make test`: **298 passed** (was 286), 2 deselected. `make lint`: clean.
  `make ui-check`: passed, now also checking the companion in view at 1440×900 and 390×844, steps ticking by hand,
  the toast top right, the chat chips and the act-by dates. Screenshots: `docs/img/v3/p1/` (looked at: companion
  opens at the top at both sizes; steps tick on a manual run; five-dot timeline with no overlaps; chat entry in the
  top bar). Seen for later phases: the mobile top bar wraps onto three lines (U27), and the KPI count-up can still
  be running when a screenshot is taken (U29).

- [x] **Phase 2. Make the AI matter** (2026-11-11, commit `e93912d`). Done: A1-A6 (DECISIONS D-142..D-147).
  Quillnote (Layer 2, prose traps): AI risk 73 vs basic check 25; the AI finds the notice period, the step-up and
  the hard cancel the basic check misses, and "seventy-two hours" -> act by Day 4 (basic: Day 7, too late).
  Penwright still 87 on both paths. `make test`: **310 passed** (was 298), 2 deselected. `make lint`: clean.
  `make ui-check`: passed, now with the Quillnote path (companion 73, AI vs basic panel, Cancel -> email + ACTION
  NEEDED -> simulated PayPal Automatic payments -> polled until CANCELLED). Two of four ui-check runs timed out on a
  page `load` (server answered in < 1 s throughout; most likely the AG Grid/Charts CDN): U30 vendoring fixes that.
  Screenshots: `docs/img/v3/p2/` (looked at: Quillnote checkout, companion, AI vs basic panel, ACTION NEEDED card).
  Seen for Phase 3: raw enums and `llm` source strings in the findings grid (U24), the delivery lines (U4), and
  the Quillnote card still offering Keep/Cancel plus a "cancel Nov 13" timer text while the handoff is open.

- [x] **Phase 3. UI restructure** (2026-11-11, commit `7b39592`). Done: U1-U30 and B9 (DECISIONS D-148..D-157).
  `/` is Priya's product view (`/user`, `/me` redirect); demo controls are a presenter bar behind `?demo=1` / D;
  companion, shop and evidence page restructured; AG Grid / Charts vendored. `make test`: **317 passed** (was 310),
  2 deselected. `make lint`: clean. `make ui-check`: passed (empty state, D key, companion order, welcome-only shop,
  merged card, one Keep / Cancel pair, U12 card, clause highlight, audit drawer with routine hidden, evidence tabs,
  390 px layout + bottom sheet, Start demo with all three answers on the card, Quillnote; no CDN requests).
  Penwright still 87, Quillnote 73. Screenshots: `docs/img/v3/p3/` (looked at: companion desktop + mobile sheet,
  Day 5 card with band, Day 11 with presenter bar, email modal with highlight, evidence summary, shop). `make sandbox-ui-check`:
  passed against the real PayPal sandbox (commit `74010ed`; the check was stale since D-120 and now serves the SDK
  button path). Left for Phase 5: the
  video narration still says "Day 7"; scenes.json only has its targets updated.

- [x] **Phase 4. Submission docs** (2026-11-11, commit `268d9e5`). Done: S1-S6 and B12 (DECISIONS D-158, D-159).
  README restructured (scannable; links are placeholders until the deploy and video). New `docs/SUBMISSION.md`,
  `docs/ARCHITECTURE.md` and `docs/TROUBLESHOOTING.md`. The spec and the v1-v2 history moved to `docs/archive/`.
  `render.yaml` deploys `prototype-v3`, mock by default; sandbox mode seeds the plans at start. LICENSE is the
  standard MIT text. `make test`: **317 passed**, 2 deselected. `make lint`: clean. `make ui-check`: passed.
  No UI changes, so no new screenshots.

- [x] **Phase 5. Video tooling** (2026-11-11, commit `83e3e19`). Done: V1-V3 (DECISIONS D-160..D-164).
  `scenes.json` has the ten v3 beats, 170 s with the PayPal clip (155 s without), cap 175 s; dates are `{on:N}`
  placeholders so the narration says "Act by Nov 18 (the terms allow Nov 19)" on any recording day. New
  `record_demo.py` (Playwright; mock or sandbox with pre-approved subscriptions from `make seed ARGS=--demo-subs`,
  which now approves Penwright and Quillnote), `make_voiceover.py` (your audio or edge-tts; ffprobe; fails if a
  voice is longer than its scene) and `make_video.sh`; `build_video.py` now mixes the voice-over, can burn captions,
  uses `-preset veryfast`, trims to 178 s and ffprobe-checks < 180 s. `make demo-video` runs the whole pipeline.
  `make demo-video-check`: passes (one warning: the hand-recorded clip isn't there yet). `make test`: **328
  passed** (was 317), 2 deselected. `make lint`: clean. `make ui-check`: passed (one earlier run failed on a
  720.00003 px companion vs 720 px; the check now allows 0.5 px). Verified for real: a full mock take recorded
  with no problems (every scene within its time), and a build with stand-in tones and a stand-in clip through a
  portable ffmpeg gave a 170.0 s `demo.mp4` (155.0 s without the clip), captions at the bottom, Quillnote in its
  slot. Not run here: edge-tts (the real voice) and a sandbox take; ffmpeg/ffprobe aren't installed on this machine.

- [x] **Phase 6. UI baseline** (commit `9f30e0d`, pushed).

## Phase 7: Sign-in, intro, deploy (docs/PHASE7_PLAN.md), branch `phase7-webapp`

Branch `phase7-webapp` was made from `prototype-v3` at `9f30e0d` ("v3: Phase 6 UI baseline"). All Phase 7 work is
committed there. When the steps are done, `phase7-webapp` is merged into `main` (`--no-ff`) and Render deploys
`main` (render.yaml's branch changes from `prototype-v3` to `main` in Step 7). Steps (rows P7-V, P7-1..P7-8 in the
FIX_PLAN Coverage checklist): V video tooling v2, 1 auth core, 2 intro + login pages, 3 dashboard additions,
4 shop + session, 5 mobile pass, 6 auth tests + tooling, 7 Render deploy, 8 demo video.

- [x] **Plan** (2026-11-12): Phase 7 section and checklist rows added to FIX_PLAN. No step started.
- [x] **Step V. Video tooling v2** (2026-11-12, commit `33ca54f`, DECISIONS D-184..D-187). scenes.json v2 with the
  13-scene storyboard (175 s; mock gives the sandbox-only PayPal proof scene's 10 s to 09_proof_app). New
  `demo-video/stage/` (rendered frame by frame by `record_stage.py`), per-word voice timings (edge-tts 7.3.1
  WordBoundary), recorder at 1600x900 with the real URL log and a yellow glow, overlay build with zoompan.
  `demo-video-check`: passes (warnings: 05_signin pending, hosted URL empty). `demo-video-preview`: about 45 s.
  A mock test take through the whole pipeline (not the final video) ran with no recorder problems and gave a
  175.00 s `demo.mp4` (ffprobe). `test`: **356 passed** (was 328), 2 deselected. `lint`: clean. The sandbox take
  (PayPal proof scene) is not run yet.
- [x] **Step 1. Auth core** (2026-11-12, commit `dc17e9f`, DECISIONS D-178..D-180). New `app/auth.py` (signed
  `sg_session` cookie with stdlib HMAC, credential check, 5 failed sign-ins per minute per IP, `AuthMiddleware`) and
  `app/routes/auth.py` (`GET/POST /login`, `POST /logout`; `next` local paths only). Settings `DEMO_PASSWORD`,
  `SESSION_SECRET` (random per process in mock if empty), `SESSION_HOURS`; sandbox refuses to start without the two
  secrets. Signed out: HTML -> 303 to `/login?next=`, `/api/*` -> 401; a different `?user=` -> 403; R5 unchanged.
  `login.html` is a plain form for now (Step 2 styles it and adds the intro at `/`; until then signed-out `/`
  redirects to sign-in). Fixtures sign in by default, `anon_client` added, the R5 tests that used `?user=intruder`
  now sign in as the intruder (`as_user`), `tests/test_auth.py` smoke tests (full set in Step 6). `ui_check.py`,
  `record_demo.py` and `check_scenes.py` sign in via `scripts/signin.py` (DEMO_PASSWORD from .env, clear error if
  missing); `record_stage.py` needed no change (only `/healthz`). `test`: **374 passed** (was 356), 2 deselected.
  `lint`: clean. `ui-check`: passed. `demo-video-check`: passes (same two warnings).
- [x] **Step 2. Intro + login pages** (2026-11-12, commit `e9087ae`, DECISIONS D-181). Signed out, `/` renders
  `intro.html` (what SubGuard is + tagline, how it works with PayPal in 3 steps, what the AI does, Sign in and Browse
  the demo shops, the fictional-merchant note; every number from `landing_view`). Signed in, `/` is still the
  dashboard; `/?demo=1` still redirects to sign-in. Hero and steps are shared macros (`_hero.html`, `_steps.html`);
  the Live demo's landing markup is unchanged (whitespace-normalised diff against the previous commit). `login.html`
  extends `base.html`, styled by `auth.css`. Signed-out top bar: brand, mode badge, Demo shops, Sign in, theme
  toggle. New `tests/test_intro.py`; `ui_check.py` walks intro -> Sign in -> dashboard at 1440 and 390 px. No
  selector changes for signed-in pages, so `scenes.json` is unchanged. `test`: **391 passed** (was 374),
  2 deselected. `lint`: clean. `ui-check`: passed.
- [x] **Step 3. Dashboard additions** (2026-11-12, commit `85c488c`, DECISIONS D-182). Avatar menu: "Signed in as
  Priya · priya@…" (local part only), Dashboard, Profile, Emails, Settings, Help (opens Ask SubGuard), Sign out as a
  POST form to `/logout`; rows are 44 px and the menu is where Sign out lives at 390 px. The Presenter menu was
  already signed-in only (D-181). Settings moved to `_settings.html`: Profile (Edit name or photo), the existing
  alert preferences, Connected accounts (PayPal Connected + "Demo data" / "PayPal Sandbox"; email and SMS alerts
  Connected / Mocked, both from `integration_states`, the `/healthz` source; no secrets), Security (Change password,
  Turn on two-step sign-in), Your data (Download my activity -> `/api/audit-log.csv?user=`, Delete account disabled
  "Demo account"). Sidebar chip: "Last signed in <date>, <time> UTC" from the latest `signed_in` entry, hidden if
  none (`app/routes/account_view.py`). "+ Add a subscription" with the hint on Subscriptions; Help center and Privacy
  in the footer. Every demo-only control has `data-soon`; one handler in `user-nav.js` (now loaded by `base.html` on
  every page) toasts "Not part of this demo" and nothing else (R7). New `tests/test_account.py` (every `[data-soon]`
  is a button or link, no success wording, the handler makes no request); `ui_check.py` checks Sign out at 390 px and
  the toast. `scenes.json` uses none of the changed selectors. `test`: **397 passed** (was 391), 2 deselected.
  `lint`: clean. `ui-check`: passed.
- [x] **Step 4. Shop and session** (2026-11-12, commit `48bb8cf`, DECISIONS D-188). The middleware already lets
  `/shop` and `/shop/*` through (D-179). `shop/routes.py` reads the session with `verify_session` and passes
  `signed_in`, `user_id` and the display name to every shop template; `<body data-user>` is the session user (empty
  signed out). Signed out, the merchant page's checkout is just "Sign in to subscribe with SubGuard" to
  `/login?next=/shop/<merchant>` (no PayPal button, companion or checkout script). Signed in, a "Signed in as Priya"
  chip in the shop header. `checkout.js`, `checkout_sandbox.js` and `companion.js` use `document.body.dataset.user`;
  no call carries a `?user=`; "Open SubGuard ↗" goes to `/` (the 4-second refresh does the rest). New
  `tests/test_shop_session.py` (signed-out create / mock-approve / register / demo-window return 401; signed-out and
  signed-in shop markup; JS never reads `?user=`). `demo-video-check` passes, also live with `--base-url` (06_shop and
  07_approve selectors unchanged: the recorder is signed in). `test`: **406 passed** (was 397), 2 deselected.
  `lint`: clean. `ui-check`: passed.
- [x] **Step 5. Mobile pass** (2026-11-12, commit `ca03695`, DECISIONS D-189). Audited at 390x844 signed out
  and signed in (intro, login, every dashboard section and menu, shop, companion, Live demo). Three issues, all fixed
  in CSS under 640 px: top-bar Sign in 59x34 -> 44 px tall; Presenter menu ran off screen (471 px scroll width) ->
  opens from the right; Live demo day scrubber 13.3 px -> 16 px (rule for all fields on phones). Desktop 1440 px
  shots unchanged. `ui_check.py` checks all three and saves `dashboard-390`; shots in `docs/img/v3/p7/mobile/`
  (intro signed out, login, dashboard signed in). `test`: **406 passed**, 2 deselected. `lint`: clean.
  `ui-check`: passed.

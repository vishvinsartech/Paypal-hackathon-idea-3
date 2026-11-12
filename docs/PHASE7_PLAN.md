\# SubGuard Phase 7 runbook: what to paste where, in order



Follow the tasks \*\*top to bottom\*\*. Each task says \*\*where\*\* to work:

\- 🖥️ \*\*PowerShell:\*\* your terminal in the project folder, with the venv on.

\- 🤖 \*\*Claude Code:\*\* paste the prompt into Claude Code.

\- 🌐 \*\*Browser:\*\* something you click yourself.



\*\*Already done:\*\* the Phase 6 baseline is committed and pushed (`9f30e0d`), you're on the new branch `phase7-webapp`, and ffmpeg 9.0.2 works.



\*\*Deadline:\*\* 13 Nov, 01:30 IST (12 Nov, 12:00 PST). Rough times are given per task. If you fall behind, cut, in this order: Task 6's demo-only extras, then the zooms in the video. Never cut Tasks 4, 9 or 10.



\*\*Rules for every Claude Code task:\*\*

1\. Start each task in a \*\*fresh Claude Code session\*\* (type `/clear`, or close and reopen it).

2\. Paste the prompt exactly. Wait until it says it committed and pushed.

3\. Do the \*\*✅ Check\*\* yourself before going to the next task.

4\. If something breaks, use the \*\*Recovery prompt\*\* at the bottom.



\*\*How to open Claude Code\*\* (each time you need it):

```powershell

cd C:\\Users\\vinee\\Documents\\paypal-SubGuard\\Paypal-hackathon-idea-3

.venv\\Scripts\\Activate.ps1

git status          # must say: On branch phase7-webapp

claude

```



\---



\## Task 1: Put the plan in the repo (🖥️ PowerShell, 5 min)



The prompts below tell Claude Code to read the plan from a file, so it has to exist first.



```powershell

notepad docs\\PHASE7\_PLAN.md

```

Notepad asks to create the file. Click \*\*Yes\*\*, paste the whole plan (the "SubGuard: sign-in, intro page, dashboard polish…" text), delete the first two lines ("Ready for review" and "Select text to add comments on the plan"), then save and close.



✅ \*\*Check:\*\* `Get-Content docs\\PHASE7\_PLAN.md -TotalCount 3` shows the plan's title.



\---



\## Task 2: Plan rows in FIX\_PLAN (🤖 Claude Code, 10 min)



```

I'm on branch phase7-webapp, made from prototype-v3 at 9f30e0d ("v3: Phase 6 UI baseline", already committed and pushed). All Phase 7 work happens on this branch; at the end I'll merge it into main and deploy main. I'm on Windows (PowerShell).



Read CLAUDE.md, docs/PHASE7\_PLAN.md, docs/FIX\_PLAN.md and docs/PROGRESS.md.



Only do this:

1\. In docs/FIX\_PLAN.md, add a "Phase 7: Sign-in, intro, deploy" section in the same format as the existing phases, with one checklist row each for: Step V (video tooling v2), Step 1 (auth core), Step 2 (intro + login pages), Step 3 (dashboard additions), Step 4 (shop + session), Step 5 (mobile pass), Step 6 (auth tests + tooling), Step 7 (Render deploy), Step 8 (demo video).

2\. In docs/PROGRESS.md, add a Phase 7 entry noting the branch and the merge-to-main plan.

3\. Commit docs/PHASE7\_PLAN.md, FIX\_PLAN.md and PROGRESS.md as "v3: Phase 7 plan" and push.



Do not start any step.

```



✅ \*\*Check:\*\* `git log --oneline -2` shows "v3: Phase 7 plan" on top of "v3: Phase 6 UI baseline".



\---



\## Task 3: Video tooling v2 (🤖 Claude Code, 1.5–2 h)



This makes the video look like your colleague's: a word-by-word headline, the app inside a browser frame, animated slides, a chapter bar and an end card. Nothing is recorded yet. \*\*If it passes 2 hours,\*\* tell it: "Commit what works now and stop." Then move on to Task 4.



```

Read demo-video/README.md, scenes.json, check\_scenes.py, record\_demo.py, make\_voiceover.py, build\_video.py, videolib.py, make\_video.sh, tests/test\_video\_tooling.py, and docs/PHASE7\_PLAN.md (Step 6 and Step 8 only).



Goal: turn the video from "raw screen recording + captions" into a presented product video, in the style described below. Keep every existing rule: scenes.json is the single source of truth, never extend a scene, hard cap under 180 s verified with ffprobe, -preset veryfast, continue past failed actions and list them at the end, and both mock and sandbox modes work. Do NOT record the final video now. Do not change app code, except the highlight colour if the highlight lives in the app.



Target style (copy the structure, use SubGuard's own brand colours and fonts from app/static):

\- 1920x1080, 30 fps, at most 175 s. Chapters: Title → Problem → How it works → Live product → Close.

\- Every frame has the same chrome: a small mono kicker top-left (e.g. "// live · the shop"), the SubGuard logo top-right, a large headline under the kicker, and a bottom progress bar split into chapter segments that fill as the video plays.

\- The headline IS the narration, revealed word by word in sync with the voice-over. Key words use the accent colour; mark them in scenes.json as \*word\*. Show at most about 14 words; older words scroll away.

\- Problem and How-it-works are motion-graphic slides (HTML/CSS), not recordings: cards, icons, numbers and arrows appear on cue when the matching word is spoken.

\- App scenes: the recording sits inside a browser-window frame (three dots, a URL bar with the REAL host and path, and a pill "LIVE · Demo data" or "LIVE · PayPal Sandbox" read from /healthz), centred on a dark brand gradient under the headline. Never fake the URL or the mode.

\- Highlights: a thick yellow glow box around the element being discussed (replace the current teal outline), plus an optional slow zoom into part of the recording.

\- PayPal proof scene: real PayPal sandbox page(s) in the same frame, only when recording in sandbox mode. In mock mode, skip it and lengthen the in-app proof scene instead.

\- Close: three pillar cards, then an end card with the logo, tagline, chips (AI reads the fine print · Code decides · PayPal enforces · Live on Render), the GitHub URL and the hosted URL.

\- Audio: continuous voice-over, plus the existing optional --music bed.



Build it like this (keep each new file under 300 lines):

1\. scenes.json v2. Each scene gets "kind": "card" | "slide" | "app" | "paypal", plus "chapter", "kicker" and "narration" (with \*accent\* markup). Slides add "slide": "<id>" and "cues": \[{"word": "...", "show": "<element id>"}]. App scenes keep "actions" and may add "zoom": {"at": s, "rect": \[x, y, w, h], "dur": s}. A scene may be "pending": true (check\_scenes warns instead of failing). check\_scenes.py validates v2, still checks every selector and the 125 wpm fit, and checks that every cue word appears in that scene's narration.

2\. make\_voiceover.py writes per-word timings to out/words.json. With edge-tts, use WordBoundary events (newer edge-tts versions need boundary="WordBoundary" passed to Communicate; check the installed version). For my own audio/<scene>.wav, spread the words evenly over the clip length. Keep captions.srt.

3\. demo-video/stage/ (stage.html, stage.css, stage.js) draws the chrome, the word-by-word headline from words.json, the progress bar, every slide (one <section> per slide, with ids for cues), the cards, and, for app/paypal scenes, the browser frame with a solid hole where the recording goes.

4\. record\_stage.py plays the stage in Playwright along the real timeline (out/timing.json from the app recording plus words.json) and records out/stage.webm at 1920x1080.

5\. record\_demo.py records the app at a viewport that matches the hole (e.g. 1600x900, set in scenes.json) so text stays sharp. It runs app/paypal scenes only; slide/card scenes just hold their time, so timing.json stays aligned.

6\. build\_video.py overlays out/screen.webm into the hole of out/stage.webm (overlay at the hole's x,y, scaled, with per-scene zoom via crop/scale; no chromakey), then mixes the audio as now. Keep all duration checks.

7\. Pipeline order: voiceover → record\_demo → record\_stage → build. I'm on Windows (PowerShell): make every video task runnable through python scripts/tasks.py (demo-video-check, demo-video-preview, demo-video) without bash; keep make\_video.sh as a thin wrapper for Mac/Linux. ffmpeg and ffprobe are on PATH (ffmpeg 9.0.2). demo-video-preview renders only the stage, using scene durations and a grey placeholder in the hole, at low quality in about a minute, so I can check timing without recording the app.

8\. Write the storyboard below into scenes.json, regenerate VIDEO\_SCRIPT.md, and update demo-video/README.md.

9\. tests/test\_video\_tooling.py: the v2 schema, cue words exist in the narration, the total is ≤ 175 s, word timings are increasing and inside their scene, \*accent\* markup is parsed, the mode pill comes from /healthz, and pending scenes warn but don't fail.



Storyboard (≤ 175 s, about 125 wpm; rewrite the words to fit, keep the beats):

| # | kind | s | kicker | beat |

|---|---|---|---|---|

| 01\_title | card | 6 | // PayPal AI Hackathon 2026 | SubGuard logo + "AI reads the fine print. PayPal enforces the outcome." |

| 02\_problem | slide | 16 | // the problem | Free trials are built to be forgotten. Priya starts one with PayPal. Fine-print cards appear (short notice, step-up price, auto-renew), each getting a red ✗ as it is named. |

| 03\_problem\_cost | slide | 14 | // the problem | She only finds out on her statement. Use a statistic ONLY if it comes from a real source shown on screen in small text; if you can't verify one, use no number. |

| 04\_how | slide | 22 | // how it works | Diagram builds on cue: Priya → PayPal checkout → SubGuard (AI reads the terms and quotes them word for word) → code decides → PayPal cancels before the deadline, only with her OK or a safety timer she saw. |

| 05\_signin | app | 10 | // live · sign in | Intro page → Sign in as Priya (password masked) → her dashboard. Mark it "pending": true; Step 6 fills it in once the sign-in pages exist. |

| 06\_shop | app | 22 | // live · the shop | Penwright → Subscribe with PayPal → companion: risk 87, the real deadline, the PayPal plan check. Yellow box on the quoted clause, slow zoom on it. |

| 07\_approve | app | 12 | // live · PayPal | Approve → Open SubGuard → the card appears on her dashboard. |

| 08\_checkin | app | 20 | // live · day 5 | "Keep your Penwright trial?" → Cancel → the email with the clause highlighted. |

| 09\_proof\_app | app | 14 | // proof | Day 11: cancelled through PayPal, audit chain verified. |

| 10\_ai\_vs\_basic | app | 15 | // why AI | Quillnote: the notice period is written in words; the basic check misses it, the AI finds it, code acts by Nov 16. |

| 11\_paypal\_proof | paypal | 10 | // proof in PayPal | Sandbox only: the subscription shows CANCELLED in PayPal itself. |

| 12\_pillars | slide | 8 | // what it means | Three cards: AI reads · Code decides · PayPal enforces. |

| 13\_end | card | 6 | // SubGuard | End card: chips, GitHub URL, hosted URL. |



When done: run demo-video-check and demo-video-preview, give me the preview file path, and list every storyboard beat that doesn't match the current app. Run test and lint. Commit as "v3: Phase 7 video tooling v2", push, and tick the Step V row in docs/FIX\_PLAN.md with the hash.

```



✅ \*\*Check:\*\*

1\. Open the preview file it names (double-click it in Explorer) and watch it once \*\*with sound\*\*. The headline words should land on the spoken words, the slides should build on cue, and the chapter bar should fill.

2\. If the timing is off, tell Claude Code which scene and what time you saw (for example "04\_how: the PayPal box appears 1 s early"), in the same session.

3\. `python scripts/tasks.py test` is green.



\---



\## Task 4: Auth core (🤖 Claude Code, 1–1.5 h): Plan Step 1



First, 🖥️ add a password to your local `.env`, which is never committed. Pick your own value:

```powershell

notepad .env

```

Add a line `DEMO\_PASSWORD=<your-password>`, then save. Remember the password: it goes on Render and into the submission text later.



```

Read docs/PHASE7\_PLAN.md, the "Context" section and "Step 1: Auth core" only. Also read app/config.py, app/main.py (create\_app and validate\_settings), app/routes/user\_page.py, the audit logging and email-masking code, data users.json, and tests/conftest.py.



Build Step 1 exactly as written:

\- app/config.py: DEMO\_PASSWORD (no default), SESSION\_SECRET (random per-process value in mock mode if empty), SESSION\_HOURS (default 8). Sandbox mode with either secret missing fails at startup and names the variable, the same way validate\_settings does. Mock mode without DEMO\_PASSWORD must still start.

\- .env.example: document both variables, with a placeholder value and no real password.

\- New app/auth.py (under 300 lines): sign and verify the sg\_session cookie (base64 of user\_id|expiry plus HMAC-SHA256, stdlib only, no itsdangerous), credential check (email case-insensitive from users.json, password with hmac.compare\_digest), the in-memory rate limiter (5 failed sign-ins per minute per IP), and the access middleware with the exact public list from the plan.

\- New app/routes/auth.py: GET /login?next=, POST /login, POST /logout. next must be a local path ("/..." but not "//..." and no scheme); anything else becomes "/". The generic error is "Email or password is wrong". In mock mode without DEMO\_PASSWORD, show "Sign-in is off: set DEMO\_PASSWORD in .env".

\- For now, make login.html a plain working form (email, password, error line). Step 2 styles it.

\- Middleware: set request.state.user\_id. Signed-out HTML gets 303 to /login?next=…; signed-out /api/\* gets 401 JSON. A ?user= that differs from the session user gets 403. Do not change route signatures or R5 filters.

\- Audit: signed\_in, sign\_in\_failed, signed\_out with actor user and decision allowed/blocked. Mask the email with the existing helper. Never log the password.

\- Cookie: HttpOnly, SameSite=Lax, Secure only when the request scheme is https.



Leave / as it is for now (Step 2 adds the intro page). Temporarily, signed-out / may redirect to /login.



Fix tests/conftest.py so the existing suite still passes: client and demo\_client set demo\_password and sign in by default; add anon\_client. Add a few smoke tests for login and logout; the full test\_auth.py comes in Step 6.



If ui-check or the video tooling now fail only because they need sign-in, make scripts/ui\_check.py, demo-video/record\_demo.py, record\_stage.py and check\_scenes.py sign in first with DEMO\_PASSWORD from .env (fail with a clear message if it is missing).



Add D-178 (cookie auth, no server sessions), D-179 (public vs protected routes, the ?user= 403 rule, R5 stays the data guard) and D-180 (password from env only) to docs/DECISIONS.md, and an Auth section to docs/ARCHITECTURE.md.



Run test, lint and ui-check. Commit as "v3: Phase 7 auth core", push, and tick the Step 1 row in FIX\_PLAN with the hash.

```



✅ \*\*Check\*\* (🖥️ start the app with the dev command from CLAUDE.md, then 🌐 use a \*\*private/incognito\*\* window):

\- `http://127.0.0.1:8000/?demo=1` sends you to `/login`.

\- A wrong password fails; the right one works.

\- `http://127.0.0.1:8000/api/subscriptions` in a fresh private window gives a 401.



\---



\## Task 5: Intro page and sign-in page (🤖 Claude Code, 45 min): Plan Step 2



```

Read docs/PHASE7\_PLAN.md "Step 2: Intro page at / when signed out". Also read app/routes/user\_page.py, app/routes/landing.py (landing\_view), app/templates/\_landing.html, base.html, login.html, and the shop's fictional-merchant footer note.



Build Step 2:

1\. home(): with no session, render a new intro.html. Signed in, / stays the dashboard. Remove any temporary redirect from Step 1.

2\. Move the shared hero and "how it works" steps out of \_landing.html into partials (e.g. \_hero.html, \_steps.html). Use them in both \_landing.html (Live demo) and intro.html. The Live demo must look exactly as before.

3\. intro.html, short, with every number from landing\_view(settings) and no hardcoded prices:

&#x20;  - One line on what SubGuard is, plus "AI reads the fine print. PayPal enforces the outcome."

&#x20;  - How it works with PayPal in 3 steps, worded as in the plan ("only with your OK or a safety timer you saw").

&#x20;  - What the AI does: reads the fine print, finds traps (short notice, step-up prices), quotes them word for word. "Code, not the AI, makes every decision."

&#x20;  - Buttons: "Sign in" (primary, /login) and "Browse the demo shops" (/shop).

&#x20;  - The existing fictional-merchant footer note.

4\. Style login.html with a new app/static/auth.css: labelled email and password fields, the error line, a "Back" link to /, and a "Demo account: Priya" hint (no password shown, no sign-up link). Inputs font-size ≥ 16px, button ≥ 44px tall.

5\. Signed-out top bar: brand, "Demo shops", "Sign in". No Presenter menu.



Add D-181 (/ switches between intro and dashboard). Update the selector contract if tests, ui\_check or scenes.json depend on it. Run test, lint and ui-check. Commit as "v3: Phase 7 intro + login pages", push, and tick FIX\_PLAN.

```



✅ \*\*Check:\*\* in a private window, `/` shows the intro. Read it as a judge would. Click both buttons.



\---



\## Task 6: Dashboard additions (🤖 Claude Code, 45 min): Plan Step 3



```

Read docs/PHASE7\_PLAN.md "Step 3: Dashboard additions" and rule R7 in CLAUDE.md. Also read app/templates/base.html (avatar menu around lines 51-61), home.html, app/static/user-nav.js, the Settings panel template, /healthz, the audit CSV endpoint and the Zapier state helper.



Real features:

1\. Avatar menu: "Signed in as Priya · priya@…" (masked), then Profile, Settings, Help, and Sign out as a POST form to /logout. It must be reachable on phones (≤640px), where the avatar menu holds Emails and Settings.

2\. The Presenter menu shows only when signed in.

3\. Settings → "Connected accounts" card: PayPal "Connected" plus the real mode from the same source /healthz uses ("Demo data" or "PayPal Sandbox"); the email and SMS alerts row shows the Zapier state (connected or mocked). Never print secrets.

4\. Settings → "Download my activity" links to the existing audit CSV endpoint.

5\. "Last signed in …" in the sidebar user chip, from the latest signed\_in audit entry; hidden if there is none.



Demo-only controls, all with one data-soon attribute. One handler in user-nav.js shows the toast "Not part of this demo" and does nothing else; nothing may claim an action happened (R7):

\- "+ Add a subscription" on the Subscriptions panel, with the hint "SubGuard adds subscriptions you start with PayPal".

\- Profile: edit name or photo.

\- Settings → Security: "Change password" and "Turn on two-step sign-in".

\- "Delete account": disabled, labelled "Demo account".

\- Footer: Help center and Privacy links.



Add D-182 (demo-only controls use data-soon). Add a test that every \[data-soon] element is a button or link and that the page has no success wording for them. Run test, lint and ui-check. Commit as "v3: Phase 7 dashboard additions", push, and tick FIX\_PLAN.

```



✅ \*\*Check:\*\* sign in, click every new control once, then sign out from the avatar menu. Do it once at normal width and once at phone width (F12 → device toolbar → 390 px).



\---



\## Task 7: Shop and session (🤖 Claude Code, 30 min): Plan Step 4



```

Read docs/PHASE7\_PLAN.md "Step 4: Shop and session". Also read shop/routes.py, the merchant page template, shop/static/checkout.js, shop/static/checkout\_sandbox.js and app/static/home.js (the 4-second refresh).



Build Step 4:

1\. Shop pages stay public; confirm the middleware allows /shop\*.

2\. shop/routes.py reads the session with the verify function from app/auth.py and passes signed\_in and user\_id to templates. Put the session user on <body data-user="…"> (empty when signed out).

3\. Signed out: Subscribe becomes the link "Sign in to subscribe with SubGuard" to /login?next=/shop/<merchant-slug>, built from the current merchant.

4\. Signed in: a small "Signed in as Priya" chip in the shop header.

5\. checkout.js and checkout\_sandbox.js stop reading ?user= from the URL and use document.body.dataset.user. Remove any leftover user query param from the create, mock-approve and register calls that could trip the 403 rule.

6\. After checkout, "Open SubGuard ↗" goes to "/". No new reflection logic.

7\. Add a test: signed-out checkout APIs return 401.



Check that the video scenes 06\_shop and 07\_approve still pass demo-video-check; fix their selectors if needed. Run test, lint and ui-check. Commit as "v3: Phase 7 shop + session", push, and tick FIX\_PLAN.

```



✅ \*\*Check (the most important one):\*\*

1\. In a private window, open `/shop/penwright`. You should see "Sign in to subscribe". Click it, sign in, and you should land back on the shop page.

2\. Subscribe, then click "Open SubGuard ↗". The new card should appear on the dashboard within about 4 seconds.

3\. Open `/api/audit-log/verify`. It should still be OK.



\---



\## Task 8: Mobile pass (🤖 Claude Code, 30 min): Plan Step 5



```

Read docs/PHASE7\_PLAN.md "Step 5: Mobile layout pass", app/static/dashboard.css (≤640px rules), auth.css and scripts/ui\_check.py.



1\. With Playwright at 390x844, signed out and signed in, check / (intro), /login, / (dashboard, every tab via the bottom tab bar), /shop, /shop/penwright and /?demo=1. For each page, report in a table: horizontal scroll (scrollWidth > innerWidth), any input/select with computed font-size < 16px, Sign in / Sign out tap targets < 44x44px, and anything cut off or overlapping (look at the screenshot).

2\. Fix every issue with CSS where possible. Desktop must not change; re-check the desktop shots.

3\. Add 390px screenshots of / signed out, /login and / signed in to scripts/ui\_check.py and the shots folder.



Run test, lint and ui-check. Show me the before/after table. Commit as "v3: Phase 7 mobile pass", push, and tick FIX\_PLAN.

```



✅ \*\*Check:\*\* open the three new 390 px screenshots in the shots folder and look at them.



\---



\## Task 9: Auth tests and the video sign-in scene (🤖 Claude Code, 45 min): Plan Step 6



```

Read docs/PHASE7\_PLAN.md "Step 6: Tests and tooling for the sign-in wall". Also read tests/conftest.py, scripts/ui\_check.py, demo-video/record\_demo.py, record\_stage.py, check\_scenes.py, scenes.json and VIDEO\_SCRIPT.md.



1\. Create tests/test\_auth.py:

&#x20;  - login works; wrong password fails; the 6th failed attempt within a minute is rate-limited (patch time, no sleep)

&#x20;  - tampered payload, expired, and wrong-signature cookies are rejected

&#x20;  - open redirect blocked: next=https://evil.example, //evil.example, /\\evil.example and javascript:… all fall back to /

&#x20;  - signed out: / shows the intro; /?demo=1 → 303 to /login?next=…; /api/\* → 401 JSON; /subscriptions/x redirects

&#x20;  - a ?user= different from the session user → 403

&#x20;  - logout clears the cookie and later requests are signed out

&#x20;  - signed\_in, sign\_in\_failed and signed\_out audit entries exist, the email is masked, and the password never appears in the audit file

&#x20;  - shop pages return 200 signed out; checkout create and register return 401 signed out

&#x20;  - mock mode without DEMO\_PASSWORD starts and shows "Sign-in is off"; sandbox mode without SESSION\_SECRET or DEMO\_PASSWORD fails at startup naming the variable

2\. Make sure ui\_check.py, record\_demo.py (httpx client AND Playwright context), record\_stage.py and check\_scenes.py sign in first with DEMO\_PASSWORD from .env, failing clearly if it is missing.

3\. scenes.json: fill in scene 05\_signin and remove "pending": intro page → click Sign in → type the email → type the password (masked field; never write the password into scenes.json, narration, captions or words.json) → the dashboard. Fix any selectors in the other app scenes that Steps 2–4 changed.

4\. Run demo-video-check and demo-video-preview; regenerate VIDEO\_SCRIPT.md.

5\. Update CLAUDE.md: how to sign in locally, the new env vars, the video commands.



Run test, lint and ui-check. Commit as "v3: Phase 7 auth tests + tooling", push, and tick FIX\_PLAN.

```



✅ \*\*Check\*\* (🖥️, replace the placeholder with your real password):

```powershell

git grep -n "<your-password>"

```

It should print \*\*nothing\*\*. Your password must not be in any committed file.



\---



\## Task 10: Deploy to Render (1 h, four parts): Plan Step 7



\### 10a: Make it Render-ready (🤖 Claude Code)

```

Read docs/PHASE7\_PLAN.md "Step 7: Render deploy". Also read render.yaml, tests/test\_deploy.py, app/main.py (around line 110), app/routes/demo.py (around line 24) and sandbox\_buyer.py.



1\. render.yaml: add SESSION\_SECRET (generateValue: true) and DEMO\_PASSWORD (sync: false). Add --proxy-headers --forwarded-allow-ips='\*' to the uvicorn start command. Change the deploy branch from prototype-v3 to main (I'll merge phase7-webapp into main and deploy main). Keep free plan, mock mode and 1 worker. Update tests/test\_deploy.py to pin the new file exactly.

2\. main.py:110: the startup log uses $PORT and the real host, not a hardcoded 8000.

3\. demo.py:24: build the capture base from request.base\_url, not 127.0.0.1:8000.

4\. sandbox\_buyer.py stays local-only; on a non-localhost host, return a clear message that the hosted sandbox uses the JS SDK path. Add D-183 (sandbox buyer window is local-only).

5\. Search for other hardcoded "127.0.0.1", "localhost" or ":8000" outside tests, scripts and docs; list them and fix the ones the app serves.

6\. README: a "Hosted demo" section with a placeholder URL, the free-plan limits (about 50 s to wake after 15 min idle; data resets on restart; sessions survive because the secret stays the same), and "sign-in details are in the submission text".

7\. Simulate Render locally: PORT=10000 with --proxy-headers --forwarded-allow-ips='\*', send a request with X-Forwarded-Proto: https, and confirm Set-Cookie includes Secure.



Run test, lint and ui-check. Commit as "v3: Phase 7 Render-ready", push, and tick FIX\_PLAN.

```



\### 10b: Merge into main (🖥️ PowerShell)

```powershell

git checkout main

git pull origin main

git merge --no-ff phase7-webapp -m "Merge phase7-webapp: sign-in, intro, video tooling, Render deploy"

python scripts/tasks.py test

git push origin main

git checkout phase7-webapp

```

If the merge reports \*\*conflicts\*\*, stop. Open Claude Code and paste the Recovery prompt with the conflict list.



\### 10c: Create the service on Render (🌐 Browser)

1\. dashboard.render.com → \*\*New\*\* → \*\*Blueprint\*\* → choose the repo `Paypal-hackathon-idea-3`. Render reads `render.yaml` (branch `main`).

2\. When it asks for \*\*DEMO\_PASSWORD\*\*, type the same password as in your `.env`. `SESSION\_SECRET` is generated for you.

3\. Click \*\*Apply\*\* and wait for "Live". Copy the URL (`https://….onrender.com`).

4\. Smoke test, then repeat at phone width (F12 → 390 px): `/healthz` → `/` (intro) → wrong password → right password → `/shop/penwright` → subscribe → "Open SubGuard" → the card appears → `/?demo=1` → sign out.

5\. If anything fails, copy the error lines from Render's \*\*Logs\*\* tab into the Recovery prompt.



\### 10d: Put the URL in the docs (🤖 Claude Code, then 🖥️ merge again)

```

The live URL is https://<your-service>.onrender.com and the smoke test passed. Replace the placeholder URL in README.md, docs/SUBMISSION.md and the video end card (scenes.json / stage). In SUBMISSION.md the hosted link is "/" and the sign-in hint says the password is in the submission text (I'll paste it myself; never write it into any file). Add the deploy to docs/PROGRESS.md. Commit as "v3: Phase 7 deployed", push, and tick FIX\_PLAN.

```

Then run the \*\*10b commands again\*\* so `main` gets this commit. Render redeploys by itself.



\---



\## Task 11: Record the demo video (🤖 Claude Code, 1–1.5 h): Plan Step 8



\*\*Pick where to record:\*\*

\- \*\*Local in sandbox mode (recommended):\*\* shows the real PayPal pages, so scene 11 (proof in PayPal) appears. The URL bar honestly shows `127.0.0.1`; the end card carries the Render URL.

\- \*\*Render (mock mode):\*\* the URL bar shows the hosted address, but scene 11 is skipped. Visit the URL 2 minutes before recording to wake the service.



```

Record the final demo video against <http://127.0.0.1:8000 in sandbox mode | https://<your-service>.onrender.com>.



1\. Run demo-video-check against that base URL. Fix only selector or timing drift; don't change the story.

2\. Run demo-video-preview and fix timing only.

3\. Run the full demo-video (voiceover → record\_demo → record\_stage → build) through python scripts/tasks.py.

4\. Pull one frame per scene (13 frames) and check each: the headline, URL bar, mode pill and chapter bar are correct, and in 05\_signin the password field is masked and unreadable.

5\. Report the output file path, its exact length (must be under 3:00), and any scene that looked off.



Do not commit the video file or the out/ folder (check .gitignore).

```



✅ \*\*Check:\*\* watch the whole video once, start to finish, with sound.



\---



\## Task 12: Submit (🌐 Browser, 20 min, before 01:30 IST)

1\. Upload the video (YouTube: \*\*Public\*\* or \*\*Unlisted\*\*, whatever the hackathon asks for).

2\. Paste the video link into `docs/SUBMISSION.md`. Ask Claude Code: "Add the video link <url> to docs/SUBMISSION.md and README.md, commit as 'v3: Phase 7 video link' and push." Then run the \*\*10b commands\*\* once more.

3\. Make sure the GitHub repo is \*\*public\*\* and shows the MIT license.

4\. Fill in the hackathon form: the repo URL, the Render URL, the video URL, and the sign-in details (\*\*email `priya@subguard-demo.example` + your DEMO\_PASSWORD\*\*, typed only into the form).



\---



\## Recovery prompt (🤖 Claude Code, whenever something goes wrong)

```

Stop adding features. This is what is broken: <paste the error, failing test name, merge conflict list or Render log lines>.

1\. Find the root cause and explain it in 2-3 sentences before changing anything.

2\. Make the smallest fix. Don't refactor or touch other steps.

3\. Run test, lint and ui-check, then show me the result.

If the fix needs a plan change, tell me first.

```



\*\*Last resort for a task that went badly wrong\*\* (🖥️): `git reset --hard HEAD` returns to the last good commit and deletes the unfinished work from that task. Every task commits when it succeeds, so you lose at most one task.


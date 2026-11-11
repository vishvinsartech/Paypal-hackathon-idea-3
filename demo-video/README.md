# Demo video tooling

`scenes.json` is the single source of truth for the video: captions, voice-over, actions (by `data-testid`), and
durations. The cut is **170 s** with the hand-recorded PayPal clip (155 s without), capped at **175 s**, and the
final file is checked with ffprobe to be **under 180 s**. A scene is never extended: anything that runs long is
trimmed to its duration.

## Prerequisites

- `make setup` (Playwright + Chromium come with the app).
- **ffmpeg and ffprobe** on PATH (https://ffmpeg.org/download.html; on Windows e.g. `winget install ffmpeg`).
- For the generated voice: `pip install -r demo-video/requirements.txt` (edge-tts, voice `en-US-JennyNeural`).
  Not needed if you record every scene yourself (see Voice-over).
- The app running: `make dev` (mock, shows "Demo data") or, for "PayPal Sandbox" on screen, see Sandbox take below.

## Commands

| Command | What it does |
|---|---|
| `make demo-video-check` | Validates `scenes.json`: durations, the cap, 125 wpm narration per scene (dates resolved), every target is a real `data-testid`, clip rules, **no real brand names** in captions or narration. Warns if the clip is missing. Writes `VIDEO_SCRIPT.md`. `ARGS="--base-url http://127.0.0.1:8000"` also checks the running app; `ARGS=--require-clips` makes a missing clip an error. |
| `make demo-video-record` | `record_demo.py`: resets the demo, records every screen scene at 1920x1080 with Playwright (teal outline for each `highlight`, about 2.5 s), writes `out/screen.webm` + `out/timing.json`. Lists every problem (a failed action, a scene that ran over) and exits 1 if there were any. `ARGS=--headed` to watch it. |
| `make demo-video-voice` | `make_voiceover.py`: one audio file per scene, measured with ffprobe; **fails if one is longer than its scene**. Writes `out/voiceover.json` and `out/captions.srt` (narration subtitles for the YouTube upload). `ARGS=--force` re-speaks after a narration change. |
| `make demo-video-build` | `build_video.py`: cuts the scenes and the clip in order, mixes the voice-over, encodes `out/demo.mp4`, and verifies it with ffprobe. `ARGS="--require-clips --burn-captions --music licensed.mp3"`; `--dry-run` prints the cut and the ffmpeg command. |
| `make demo-video` | All four, in order, stopping at the first failure (same as `demo-video/make_video.sh`). `ARGS` go to the build. |

Windows without make: `python scripts/tasks.py demo-video [--require-clips --burn-captions]`, and likewise
`demo-video-check`, `demo-video-record`, `demo-video-voice`, `demo-video-build`.

## The beats

| # | s | Beat |
|---|---|---|
| 01_hook | 10 | "Free trials are designed to be forgotten." Priya's empty SubGuard |
| 02_shop | 15 | Penwright checkout, fine print, Terms |
| 03_companion | 25 | Verdict, act by Nov 18 (the terms allow Nov 19), PayPal check, injection ignored, consent box |
| 03b_paypal_approval | 15 | **Clip** recorded by hand: the real PayPal sandbox approval |
| 04_ai_vs_basic | 15 | Quillnote evidence page: the AI found the notice period, the basic check missed it |
| 05_checkin | 15 | Day 5 check-in band |
| 06_cancel | 30 | Cancel, PayPal first, AI email quoting the clause, Send, PayPal CANCELLED read live |
| 07_audit | 15 | Activity with R1/R2 chips, "Show raw log" filtered to R1 |
| 08_proof_scale | 20 | Day 11 proof; scale: Fair Trial partners, one tap in PayPal, the PayPal wallet |
| 09_close | 10 | Charges avoided, MIT, repo URL |

Notes for editing `scenes.json`:

- `{on:N}` in a caption or narration is the calendar date N days after a sign-up made today ("Nov 18"; spoken as
  "November 18"), so the video matches the app on whatever day you record it.
- `04_ai_vs_basic` is `"separate": true`: it's recorded after the main take (a Quillnote trial made at Day 0 would
  fire before the Day 5 check-in), with an off-screen `"setup"` that subscribes Priya to Quillnote. The build still
  puts it in its scenes.json slot.
- `"mock_only": true` skips an action in sandbox mode; `"sandbox_subscribe"` registers a pre-approved subscription
  after the scene (sandbox only).
- Never name a real brand in a caption or narration (the check fails). Say "your email app", not a provider.

## Voice-over

Your own recording wins: put `demo-video/audio/<scene_id>.wav` (or `.mp3`) there (gitignored), at most the scene's
length. Any scene without one is spoken by edge-tts. The narration of the clip scene is voiced too; the clip's own
audio is dropped.

## Sandbox take ("PayPal Sandbox" on screen)

1. `make seed ARGS=--demo-subs`: products, plans, and pre-approved **Penwright and Quillnote** subscriptions for the
   sandbox buyer (a browser opens to approve them). Run it again before every take: each take cancels Penwright.
2. `make dev-sandbox` (needs the LLM key; the companion's review is the real model, so allow a few seconds).
3. `make demo-video`. The recorder skips "Continue to PayPal" (the clip shows PayPal's window) and registers the
   pre-approved subscriptions instead.
4. Afterwards cancel anything still ACTIVE in the sandbox (Quillnote is Layer 2: use the buyer's PayPal Automatic
   payments page).

## The PayPal approval clip (`03b_paypal_approval`)

The automated recorder can't show PayPal's real approval window (PayPal's own site, behind the sandbox buyer's
login). That 15-second moment is recorded by hand and inserted by `build_video.py` right after `03_companion`:

- file: `demo-video/clips/paypal_approval.mp4` (the folder is gitignored; never commit recordings)
- at most **15 s**. `build_video.py` trims it to the scene's `duration` and never stretches it. Its own audio is
  dropped; the scene's narration is the voice-over.
- if the file is missing, `check_scenes.py` prints a warning and the build skips the scene (the cut is then 155 s).
  `--require-clips` turns that into an error for the final build.

### How to record it

1. Run the app in **sandbox mode** with a seeded plan: `make seed`, then `make dev-sandbox`. Sandbox mode needs an
   LLM key in `.env` (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`).
2. **Log in to the sandbox buyer first.** In the browser you'll record with, open https://www.sandbox.paypal.com
   and sign in as `PAYPAL_SANDBOX_BUYER_EMAIL`, so the pop-up opens already logged in. **Never show a password, an
   email field being typed, or `.env` on screen.**
3. Set the browser window to 1920x1080 (or 16:9), close other tabs and notifications, and use a clean profile
   with no bookmarks bar, extensions or personal data.
4. Open http://127.0.0.1:8000/shop/penwright, click PayPal, then **Continue to PayPal** in the SubGuard companion
   (that part is already in the automated video; start recording just before you click the PayPal button).
5. Record **one clean take**: the PayPal window opens, shows Penwright Pro (10-day trial $0, then $24.99/month),
   you click **Agree & Subscribe**, the window closes, and the shop shows "You're subscribed. Welcome to Penwright."
6. **Trim the waiting time** (PayPal loading, the server confirming ACTIVE) so the clip is 15 s or less. Any
   editor works; with ffmpeg: `ffmpeg -ss 00:00:03 -to 00:00:18 -i raw.mp4 -an -c:v libx264 paypal_approval.mp4`.
7. Save it as `demo-video/clips/paypal_approval.mp4` and run `make demo-video-check`: the warning should be gone.
8. Afterwards, cancel the subscription (SubGuard's Cancel, or the buyer's PayPal Automatic payments page) so no
   test subscription stays ACTIVE in the sandbox.

To rehearse the same path automatically (no recording), run `make sandbox-ui-check`.

## YouTube checklist

- `make demo-video ARGS="--require-clips --burn-captions"`; the build prints the ffprobe length (must be < 3:00).
- Watch it once end to end: no password, no `.env`, no personal data, no real brand in a caption.
- Upload as **Public**; title mentions SubGuard and "PayPal Sandbox"; upload `out/captions.srt` as subtitles.
- No unlicensed music (only `--music` with a track you have the rights to).
- Paste the link into `README.md` and `docs/SUBMISSION.md`.

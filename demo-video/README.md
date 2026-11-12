# Demo video tooling (v2)

A presented product video, not a raw screen recording (DECISIONS D-184..D-187). `scenes.json` is the single source
of truth: 13 scenes, **175 s**, in five chapters (Title → Problem → How it works → Live product → Close). Every
frame has the same chrome: a mono kicker top left, the SubGuard logo top right, a large headline that **is the
narration, revealed word by word with the voice**, and a chapter progress bar at the bottom. Problem, How it works
and the pillars are motion-graphic slides that build on cue. App scenes show the real app inside a browser frame,
with the real URL and the real mode pill. A scene is never extended: anything that runs long is trimmed. ffprobe
checks the final file is **under 180 s**.

## Prerequisites

- `make setup` (Playwright + Chromium come with the app).
- **ffmpeg and ffprobe** (e.g. `winget install ffmpeg`). If a terminal was open before the install, `scripts/tasks.py`
  still finds the winget copy on Windows.
- The voice: `pip install -r demo-video/requirements.txt` (edge-tts 7, voice `en-US-JennyNeural`), unless you
  record every scene yourself (see Voice-over).
- For a take, the app running: `make dev` (mock: the pill says `LIVE · Demo data`) or a sandbox take (below).

## Commands (Windows: `python scripts/tasks.py <task>`; Mac/Linux: `make <task>`)

| Task | What it does |
|---|---|
| `demo-video-check` | Validates `scenes.json` v2: kinds, chapters in order, kickers, durations and the cap, 125 wpm per scene, every cue word in its narration, every slide/cue element in `stage/stage.html`, every app target a real `data-testid`, zoom rects, no real brands in narration. Pending scenes and an empty hosted link only warn. Writes `VIDEO_SCRIPT.md`. `--base-url URL` checks the running app's pages. |
| `demo-video-preview` | Voice-over + stage only, **no app recording**: `out/preview.mp4` (10 fps, half size, grey placeholder in the frame, voice mixed in) in about a minute. Use it to check timing with sound. |
| `demo-video` | The whole video: check → voice-over → record the app → render the stage → build → `out/demo.mp4`. Extra args go to the build (`--music licensed.mp3`). `demo-video/make_video.sh` is the same thing for Mac/Linux. |
| `demo-video-voice` | `make_voiceover.py`: one audio file per scene + `out/words.json` (each headline word's time). Fails if a voice is longer than its scene. `--force` re-speaks everything (it re-speaks a changed narration by itself). |
| `demo-video-record` | `record_demo.py`: resets the demo and records the app at 1600x900 → `out/screen.webm` + `out/timing.json` (mode from `/healthz`, every scene's start/end, every URL visited). Slide/card scenes hold their time. Lists every failed action at the end and exits 1 (pending scenes only warn). `--headed` to watch. |
| `demo-video-stage` | `record_stage.py`: renders the stage frame by frame from `timing.json` + `words.json` → `out/stage.mp4` (1920x1080, 30 fps). `--preview` is the preview's step. |
| `demo-video-build` | `build_video.py`: overlays each recorded scene into the frame's hole at its time (with its zoom), mixes the voice-over (+ `--music`), H.264 `-preset veryfast`, verifies with ffprobe, writes `out/demo.mp4` + `out/captions.srt`. `--dry-run` prints the ffmpeg command. |

## The storyboard

| # | kind | s | kicker | beat |
|---|---|---|---|---|
| 01_title | card | 6 | `// PayPal AI Hackathon 2026` | Logo + "AI reads the fine print. PayPal enforces the outcome." |
| 02_problem | slide | 16 | `// the problem` | Free trials are built to be forgotten. Priya, her PayPal checkout, three fine-print cards that each get a red ✗ |
| 03_problem_cost | slide | 14 | `// the problem` | Her statement: the first charge already taken. No reminder, no warning (no statistic: none verified) |
| 04_how | slide | 22 | `// how it works` | Priya → PayPal checkout → SubGuard (AI reads, quotes word for word) → code decides → PayPal cancels, only with her OK or a timer she saw |
| 05_signin | app | 10 | `// live · sign in` | **pending** until Phase 7 Step 6 (sign-in pages); for now her empty dashboard |
| 06_shop | app | 22 | `// live · the shop` | Penwright, fine print (glow + slow zoom), PayPal → companion: risk, act-by date, PayPal plan check |
| 07_approve | app | 12 | `// live · PayPal` | Continue to PayPal (mock: simulated approval) → her dashboard card |
| 08_checkin | app | 20 | `// live · day 5` | "Keep your Penwright trial?" → Cancel → confirm → email with the clause highlighted |
| 09_proof_app | app | 14 (24 in mock) | `// proof` | Day 11: "$24.99 never charged", audit log "chain verified ✓" |
| 10_ai_vs_basic | app | 15 | `// why AI` | Quillnote at Day 0: AI finds "seventy-two hours", act by Nov 16; the basic check says Nov 19 |
| 11_paypal_proof | paypal | 10 | `// proof in PayPal` | Sandbox only: PayPal's own Automatic payments page |
| 12_pillars | slide | 8 | `// what it means` | AI reads · Code decides · PayPal enforces |
| 13_end | card | 6 | `// SubGuard` | Logo, tagline, chips, repo URL, hosted URL |

## Editing `scenes.json`

- `narration` is spoken and shown. `*word*` or `*several words*` = accent colour. `{on:N}` = the calendar date N days
  after a sign-up made today ("Nov 18", spoken "November 18"), so the video matches the app on any recording day.
  `{fact:key}` = a number from the app (`landing_view`: `intro`, `step_up`, `notice_days`…). Never type a price.
- `cues: [{"word", "show"}]` on slides/cards: element `#show` in `stage/stage.html` appears when that word is
  spoken. Cues match in order, so a repeated word cues its next occurrence.
- App scenes: `actions` by `data-testid` (`goto`, `click`, `hover`, `type`, `press`, `wait_for`, `wait`,
  `scroll_to`, `highlight` = a thick yellow glow for 2.5 s). `setup` runs off screen first (`reset`, `day: N`,
  `subscribe: <plan>`). `mock_only` skips an action in sandbox. `zoom: {"at", "rect": [x, y, w, h], "dur"}` in
  1600x900 recording pixels, 16:9, eased in and out over 0.8 s.
- `links.hosted`: the Render URL for the end card (empty until the deploy; the check warns).
- Never name a real brand in narration or a kicker (the check fails). Say "your email app", not a provider.

## Voice-over

Your own recording wins: put `demo-video/audio/<scene_id>.wav` (or `.mp3`, gitignored) there, at most the scene's
length; its words are spread over the clip by word length. Any other scene is spoken by edge-tts with per-word
timings (`boundary="WordBoundary"`).

## Sandbox take (`LIVE · PayPal Sandbox`, plus the PayPal proof scene)

1. `python scripts/tasks.py seed --demo-subs`: products, plans and pre-approved **Penwright and Quillnote**
   subscriptions for the sandbox buyer. Run it again before every take: each take cancels Penwright.
2. `python scripts/tasks.py dev-sandbox` (needs the LLM key; the companion's review is the real model).
3. `python scripts/tasks.py demo-video`. The recorder logs in to PayPal sandbox as `PAYPAL_SANDBOX_BUYER_EMAIL` in a
   separate, **unrecorded** browser and reuses only its cookies, so no email or password is typed on camera. It
   skips "Continue to PayPal" (PayPal's window isn't automated on camera) and registers the pre-approved
   subscriptions instead.
4. Afterwards cancel anything still ACTIVE in the sandbox (Quillnote is Layer 2: the buyer's Automatic payments page).

In mock mode the PayPal proof scene is skipped and 09_proof_app holds 10 s longer, so the video is 175 s either way.

## YouTube checklist

- `python scripts/tasks.py demo-video`; the build prints the ffprobe length (must be < 3:00).
- Watch it once end to end: no password, no `.env`, no personal data, no real brand in the narration.
- Upload as **Public**; upload `out/captions.srt` as subtitles. Only `--music` with a track you have the rights to.
- Paste the link into `README.md` and `docs/SUBMISSION.md`.

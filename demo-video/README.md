# Demo video tooling

`scenes.json` is the single source of truth for the video: captions, voice-over, actions (by `data-testid`), and
durations. The whole cut, including the hand-recorded PayPal clip, must stay **at or under 175 s** (5 s under the
3-minute limit).

| Command | What it does |
|---|---|
| `make demo-video-check` (`python scripts/tasks.py demo-video-check`) | Validates `scenes.json` (durations, 125 wpm narration, every target exists in the UI, clip rules), warns if a clip file is missing, writes `VIDEO_SCRIPT.md`. Add `--base-url http://127.0.0.1:8000` to check a running app, `--require-clips` to make a missing clip an error. |
| `make demo-video` (`python scripts/tasks.py demo-video`) | `build_video.py`: cuts `out/screen.webm` (recorded scenes, from `out/timing.json`) and the clips into `out/demo_silent.mp4`, in scene order. Needs ffmpeg. `--dry-run` prints the cut and the ffmpeg command. |

The automated screen recorder and the voice-over (`record_demo.py`, `make_voiceover.py`) are milestone 9 work; see
`docs/PROGRESS.md`. `build_video.py` already reads their outputs: `out/screen.webm`, plus `out/timing.json`
shaped as `{"scenes": [{"id": "01_hook", "start": 0.0, "end": 12.1}, ...]}`.

## The PayPal approval clip (`03b_paypal_approval`)

The recorder runs in **mock mode**, so it can't show PayPal's real approval window (that's PayPal's own site, behind
the sandbox buyer's login). That 15-second moment is recorded by hand and inserted by `build_video.py` right after
`03_companion`:

- file: `demo-video/clips/paypal_approval.mp4` (the folder is gitignored; never commit recordings)
- at most **15 s**. `build_video.py` trims it to the scene's `duration` and never stretches it. Its own audio is
  dropped; the scene's narration is the voice-over.
- if the file is missing, `check_scenes.py` prints a warning and the build skips the scene (a mock-only cut is then
  150 s). `--require-clips` turns that into an error for the final build.

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
   you click **Agree & Subscribe**, the window closes, and the shop shows **"Subscribed via PayPal ✓"** with
   status **ACTIVE**.
6. **Trim the waiting time** (PayPal loading, the server confirming ACTIVE) so the clip is 15 s or less. Any
   editor works; with ffmpeg: `ffmpeg -ss 00:00:03 -to 00:00:18 -i raw.mp4 -an -c:v libx264 paypal_approval.mp4`.
7. Save it as `demo-video/clips/paypal_approval.mp4` and run `make demo-video-check`: the warning should be gone.
8. Afterwards, cancel the subscription (SubGuard's Cancel, or the buyer's PayPal Automatic payments page) so no
   test subscription stays ACTIVE in the sandbox.

To rehearse the same path automatically (no recording), run `make sandbox-ui-check`. It drives the real PayPal
window with the sandbox buyer, checks the live status cards and the "View in PayPal sandbox" link, and cancels
anything it created.

#!/usr/bin/env bash
# The whole demo video, in order, stopping at the first failure:
#   check (scenes.json, selectors, 125 wpm, brands) -> record (Playwright) -> voice-over (edge-tts or your audio/)
#   -> build (ffmpeg; ffprobe checks it's under 180 s).
# The app must already be running: `make dev` (mock, "Demo data") or, for "PayPal Sandbox" on screen,
# `make seed ARGS=--demo-subs` then `make dev-sandbox`. Extra arguments go to build_video.py
# (e.g. --require-clips --burn-captions --music licensed.mp3).
# Windows without bash: python scripts/tasks.py demo-video [build args]
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
else PY=python3; fi

"$PY" demo-video/check_scenes.py
"$PY" demo-video/record_demo.py
"$PY" demo-video/make_voiceover.py
"$PY" demo-video/build_video.py "$@"

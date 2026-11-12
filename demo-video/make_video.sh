#!/usr/bin/env bash
# The whole demo video (Mac/Linux): a thin wrapper around `python scripts/tasks.py demo-video`, which runs
#   check -> voice-over -> record the app (Playwright) -> render the stage -> build (ffmpeg; ffprobe < 180 s),
# stopping at the first failure. The app must already be running: `make dev` (mock, "Demo data") or, for
# "PayPal Sandbox" on screen, `make seed ARGS=--demo-subs` then `make dev-sandbox`. Extra arguments go to
# build_video.py (e.g. --music licensed.mp3). Windows: python scripts/tasks.py demo-video [build args]
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
else PY=python3; fi
exec "$PY" scripts/tasks.py demo-video "$@"

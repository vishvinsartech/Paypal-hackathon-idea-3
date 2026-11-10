"""Cross-platform task runner mirroring the Makefile (works on Windows without `make`).

Usage: python scripts/tasks.py <task> [args]
Tasks: setup dev dev-sandbox seed sandbox-check sandbox-ui-check reset test lint ui-check zapier-check
       demo-video-check demo-video
Extra args go to `seed` / `sandbox-check` / `sandbox-ui-check` / the demo-video tasks (e.g. `seed --demo-subs`).
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(*args: str, env: dict[str, str] | None = None) -> int:
    print("+", " ".join(args), flush=True)
    return subprocess.call(list(args), cwd=ROOT, env={**os.environ, **(env or {})})


def py() -> str:
    return str(VPY) if VPY.exists() else sys.executable


def setup() -> int:
    if not VPY.exists():
        print(f"+ creating venv in {VENV}")
        venv.create(VENV, with_pip=True)
    return (
        run(str(VPY), "-m", "pip", "install", "--upgrade", "pip")
        or run(str(VPY), "-m", "pip", "install", "-r", "requirements.txt")
        or run(str(VPY), "-m", "playwright", "install", "chromium")
    )


SERVE = ("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload")


def dev(mode: str | None = None) -> int:
    """Thin wrapper: exactly `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload` with the venv's
    Python. `dev` keeps APP_MODE from the environment / .env (default mock); `dev-sandbox` sets it to sandbox."""
    return run(py(), *SERVE, env={"APP_MODE": mode} if mode else None)


def reset() -> int:
    code = ("from app.config import load_settings; from app.store import JsonStore; s=load_settings(); "
            "st=JsonStore(s.runtime_dir, s.seed_dir, s.app_mode, pricing=s.pricing); st.reset(); print('reset ok')")
    return run(py(), "-c", code)


TASKS = {
    "setup": setup,
    "dev": lambda: dev(),
    "dev-sandbox": lambda: dev("sandbox"),
    "seed": lambda: run(py(), "scripts/seed_sandbox.py", *sys.argv[2:]),
    "sandbox-check": lambda: run(py(), "scripts/sandbox_cancel_check.py", *sys.argv[2:]),
    "sandbox-ui-check": lambda: run(py(), "scripts/sandbox_ui_check.py", *sys.argv[2:]),
    "reset": reset,
    "test": lambda: run(py(), "-m", "pytest", "-q"),
    "lint": lambda: run(py(), "-m", "ruff", "check", "."),
    "ui-check": lambda: run(py(), "scripts/ui_check.py", *sys.argv[2:]),
    "zapier-check": lambda: run(py(), "scripts/zapier_check.py", *sys.argv[2:]),
    "demo-video-check": lambda: run(py(), "demo-video/check_scenes.py", *sys.argv[2:]),
    "demo-video": lambda: run(py(), "demo-video/build_video.py", *sys.argv[2:]),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(2)
    sys.exit(TASKS[sys.argv[1]]())

"""Cross-platform task runner mirroring the Makefile (works on Windows without `make`).

Usage: python scripts/tasks.py <setup|dev|dev-sandbox|seed|reset|test|lint|demo-video-check|demo-video>
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


def dev(mode: str = "mock") -> int:
    return run(py(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000",
               "--reload", "--workers", "1", env={"APP_MODE": mode})


def reset() -> int:
    code = "from app.config import load_settings; from app.store import JsonStore; " \
           "s=load_settings(); st=JsonStore(s.runtime_dir, s.seed_dir, s.app_mode); st.reset(); print('reset ok')"
    return run(py(), "-c", code)


def not_yet(name: str, milestone: int) -> int:
    print(f"`{name}` arrives in milestone {milestone} (see docs/PROGRESS.md).")
    return 1


TASKS = {
    "setup": setup,
    "dev": lambda: dev("mock"),
    "dev-sandbox": lambda: dev("sandbox"),
    "seed": lambda: run(py(), "scripts/seed_sandbox.py") if (ROOT / "scripts/seed_sandbox.py").exists()
    else not_yet("seed", 3),
    "reset": reset,
    "test": lambda: run(py(), "-m", "pytest", "-q"),
    "lint": lambda: run(py(), "-m", "ruff", "check", "."),
    "demo-video-check": lambda: not_yet("demo-video-check", 9),
    "demo-video": lambda: not_yet("demo-video", 9),
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(2)
    sys.exit(TASKS[sys.argv[1]]())

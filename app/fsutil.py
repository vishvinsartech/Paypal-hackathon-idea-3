"""File operations that survive Windows sharing violations (D-172).

On Windows, renaming or deleting a file fails with PermissionError (WinError 32 / 5) while another thread has it
open, even for a few milliseconds. Page polls read the store and the audit log without the lock, so a Reset could
fail halfway (old subscriptions left behind) and an atomic write could fail now and then. These retry briefly.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

TRIES = 40
WAIT_S = 0.025  # up to ~1 s in all


def _retry(op: Callable[[], None]) -> None:
    for attempt in range(TRIES):
        try:
            op()
            return
        except PermissionError:
            if attempt == TRIES - 1:
                raise
            time.sleep(WAIT_S)


def replace(src: Path, dst: Path) -> None:
    _retry(lambda: os.replace(src, dst))


def unlink(path: Path) -> None:
    _retry(lambda: path.unlink(missing_ok=True))


def rmtree(path: Path) -> None:
    _retry(lambda: shutil.rmtree(path) if path.exists() else None)

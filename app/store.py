"""JSON-file store: typed access, atomic writes, one process-wide lock, corrupt-file recovery.

Rules (spec 5.3):
- Read-modify-write goes through `edit()` (sync code) or `aedit()` (async code), both under the lock.
- Async code must use `aedit()` / `alocked()`, never `edit()` directly: the asyncio lock is what
  serialises coroutines on the event-loop thread (the RLock is re-entrant per thread).
- Writes are atomic: tmp file, fsync, os.replace.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from app import models as m
from app.core.audit_log import AuditLog

T = TypeVar("T", bound=BaseModel)


def utcnow() -> datetime:
    return datetime.now(UTC)


def ts_slug() -> str:
    return utcnow().strftime("%Y%m%dT%H%M%S%fZ")


def atomic_write_text(path: Path, text: str) -> None:
    """Write via tmp + fsync + os.replace so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


class JsonStore:
    KEEP_ON_RESET = ("sandbox_ids.json",)

    def __init__(self, runtime_dir: Path, seed_dir: Path, app_mode: str = "mock") -> None:
        self.dir = runtime_dir
        self.seed_dir = seed_dir
        self.app_mode = app_mode
        self.lock = threading.RLock()
        self._alock = asyncio.Lock()
        self.warnings: list[str] = []
        self.files: dict[str, tuple[type[BaseModel], Callable[[], BaseModel]]] = {
            "state": (m.State, lambda: m.State(app_mode=self.app_mode)),
            "users": (m.UserList, lambda: self._seed(m.UserList, "users.json")),
            "merchants": (m.MerchantList, lambda: self._seed(m.MerchantList, "merchants.json")),
            "subscriptions": (m.SubscriptionList, m.SubscriptionList),
            "reviews": (m.ReviewList, m.ReviewList),
            "timers": (m.TimerList, m.TimerList),
            "alerts": (m.AlertList, m.AlertList),
            "tokens": (m.TokenList, m.TokenList),
            "usage": (m.UsageList, m.UsageList),
            "notices": (m.NoticeList, m.NoticeList),
            "sandbox_ids": (m.SandboxIds, m.SandboxIds),
            "mock_paypal": (m.MockPayPalState, m.MockPayPalState),
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        self.audit = AuditLog(self.dir / "audit_log.jsonl", self.lock, self._sim_day)

    # ---- paths / defaults ---------------------------------------------------
    def path(self, name: str) -> Path:
        if name not in self.files:
            raise KeyError(f"Unknown store file: {name}")
        return self.dir / f"{name}.json"

    def _seed(self, model: type[T], filename: str) -> T:
        seed = self.seed_dir / filename
        if seed.exists():
            return model.model_validate_json(seed.read_text(encoding="utf-8"))
        return model()

    def _sim_day(self) -> int:
        return cast(m.State, self.load("state")).sim_day

    # ---- typed read / write -------------------------------------------------
    def load(self, name: str) -> Any:
        model, default = self.files[name]
        path = self.path(name)
        if not path.exists():
            with self.lock:
                if not path.exists():
                    obj = default()
                    self._write(path, obj)
                    return obj
        try:
            return model.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, ValueError, OSError) as exc:
            return self._recover(name, exc)

    def _recover(self, name: str, exc: Exception) -> BaseModel:
        """Corrupt file: move aside, start from defaults, audit it, warn in healthz."""
        model, default = self.files[name]
        path = self.path(name)
        with self.lock:
            try:  # another thread may have recovered it already
                return model.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, ValueError, OSError):
                pass
            moved = path.with_name(f"{name}.corrupt-{ts_slug()}.json")
            if path.exists():
                os.replace(path, moved)
            obj = default()
            self._write(path, obj)
            msg = f"{path.name} was corrupt; moved to {moved.name} and reset to defaults"
            self.warnings.append(msg)
            self.audit.append(
                actor="system", event="store_corrupt_recovered", reason=msg,
                details={"file": path.name, "moved_to": moved.name, "error": type(exc).__name__},
            )
            return obj

    def _write(self, path: Path, obj: BaseModel) -> None:
        atomic_write_text(path, obj.model_dump_json(indent=2))

    def save(self, name: str, obj: BaseModel) -> None:
        model, _ = self.files[name]
        if not isinstance(obj, model):
            raise TypeError(f"{name} expects {model.__name__}, got {type(obj).__name__}")
        with self.lock:
            self._write(self.path(name), obj)

    # ---- locking ------------------------------------------------------------
    @contextmanager
    def edit(self, name: str) -> Iterator[Any]:
        """Locked read-modify-write for sync code. Saves only if the block doesn't raise."""
        with self.lock:
            obj = self.load(name)
            yield obj
            self.save(name, obj)

    @asynccontextmanager
    async def alocked(self) -> AsyncIterator[None]:
        """Hold the process-wide lock from async code (use sync `edit()` inside)."""
        async with self._alock:
            with self.lock:
                yield

    @asynccontextmanager
    async def aedit(self, name: str) -> AsyncIterator[Any]:
        async with self.alocked():
            with self.edit(name) as obj:
                yield obj

    # ---- lifecycle ----------------------------------------------------------
    def ensure_all(self) -> None:
        for name in self.files:
            self.load(name)

    def reset(self) -> None:
        """Wipe runtime data except sandbox ids and archived audit logs, then re-seed."""
        with self.lock:
            archived = self.audit.archive()
            for entry in self.dir.iterdir():
                keep = entry.name in self.KEEP_ON_RESET or (
                    entry.name.startswith("audit_log.") and entry.name != "audit_log.jsonl"
                )
                if keep:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            self.warnings.clear()
            self.audit.reload()
            self.ensure_all()
            self.audit.append(
                actor="system", event="demo_reset", reason="runtime data reset",
                details={"archived_audit_log": archived.name if archived else None},
            )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

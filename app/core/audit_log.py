"""Append-only audit log (JSON lines) with a SHA-256 hash chain.

Each line's `hash` = sha256(canonical JSON of the entry without `hash`), and the entry includes
`prev_hash`, so editing or deleting any line breaks the chain from that point on.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import fsutil

GENESIS = "0" * 64
Actor = Literal["user", "agent", "policy", "timer", "merchant_sim", "system"]
Decision = Literal["allowed", "blocked", "n/a"]
Transport = Literal["sdk", "mcp", "rest", "mock"]

SECRET_KEY_RE = re.compile(r"(token|secret|password|api[_-]?key|authorization|assertion)", re.I)
EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I)


def mask_email(text: str) -> str:
    return EMAIL_RE.sub(lambda mt: f"{mt.group(1)}***@{mt.group(2)}", text)


def mask_secrets(value: Any) -> Any:
    """Recursively mask secret-looking keys, bearer tokens and email addresses."""
    if isinstance(value, dict):
        return {
            k: ("***" if SECRET_KEY_RE.search(str(k)) and v else mask_secrets(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(v) for v in value]
    if isinstance(value, str):
        return mask_email(BEARER_RE.sub(r"\1***", value))
    return value


class AuditEntry(BaseModel):
    ts: str
    sim_day: int
    seq: int
    actor: Actor
    user_id: str | None = None
    event: str
    subscription_id: str | None = None
    rule_id: str | None = None
    decision: Decision = "n/a"
    reason: str | None = None
    transport: Transport | None = None
    paypal_request_id: str | None = None
    paypal_debug_id: str | None = None
    status_before: str | None = None
    status_after: str | None = None
    result: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str = ""


class VerifyResult(BaseModel):
    ok: bool
    entries: int
    broken_at_seq: int | None = None
    broken_at_line: int | None = None
    reason: str | None = None


def entry_hash(data: dict[str, Any]) -> str:
    body = {k: v for k, v in data.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path, lock: threading.RLock, sim_day: Callable[[], int]) -> None:
        self.path = path
        self.lock = lock
        self.sim_day = sim_day
        self.reload()

    def reload(self) -> None:
        """Pick up the last seq/hash from disk (tolerates a broken tail; verify() reports it)."""
        self._seq, self._last_hash = 0, GENESIS
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                self._seq, self._last_hash = int(data["seq"]), str(data["hash"])
            except (ValueError, KeyError, TypeError):
                continue

    def append(self, *, actor: Actor, event: str, **fields: Any) -> AuditEntry:
        with self.lock:
            fields["details"] = mask_secrets(fields.get("details") or {})
            if fields.get("reason"):
                fields["reason"] = mask_secrets(fields["reason"])
            entry = AuditEntry(
                ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                sim_day=fields.pop("sim_day", None) if "sim_day" in fields else self.sim_day(),
                seq=self._seq + 1, actor=actor, event=event, prev_hash=self._last_hash, **fields,
            )
            data = entry.model_dump(mode="json")
            data["hash"] = entry_hash(data)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._seq, self._last_hash = entry.seq, data["hash"]
            return AuditEntry.model_validate(data)

    def entries(self) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(AuditEntry.model_validate_json(line))
            except ValueError:
                continue
        return out

    def query(
        self, user: str | None = None, event: str | None = None, since_day: int | None = None,
        subscription_id: str | None = None,
    ) -> list[AuditEntry]:
        return [
            e for e in self.entries()
            if (user is None or e.user_id == user)
            and (event is None or e.event == event)
            and (since_day is None or e.sim_day >= since_day)
            and (subscription_id is None or e.subscription_id == subscription_id)
        ]

    def verify(self) -> VerifyResult:
        if not self.path.exists():
            return VerifyResult(ok=True, entries=0)
        prev, count, expected_seq = GENESIS, 0, 1
        for lineno, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except ValueError:
                return VerifyResult(ok=False, entries=count, broken_at_line=lineno, reason="unparsable line")
            seq = data.get("seq")
            if data.get("prev_hash") != prev:
                return VerifyResult(ok=False, entries=count, broken_at_seq=seq, broken_at_line=lineno,
                                    reason="prev_hash does not match previous entry")
            if entry_hash(data) != data.get("hash"):
                return VerifyResult(ok=False, entries=count, broken_at_seq=seq, broken_at_line=lineno,
                                    reason="entry hash mismatch (entry was modified)")
            if seq != expected_seq:
                return VerifyResult(ok=False, entries=count, broken_at_seq=seq, broken_at_line=lineno,
                                    reason=f"sequence gap: expected {expected_seq}")
            prev, count, expected_seq = data["hash"], count + 1, expected_seq + 1
        return VerifyResult(ok=True, entries=count)

    def archive(self) -> Path | None:
        """Rename the current log to audit_log.<timestamp>.jsonl (never deleted)."""
        with self.lock:
            if not self.path.exists():
                return None
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            target = self.path.with_name(f"audit_log.{stamp}.jsonl")
            fsutil.replace(self.path, target)  # retries while a page poll reads the log (Windows, D-172)
            self.reload()
            return target

    def to_csv(self, entries: list[AuditEntry]) -> str:
        buf = io.StringIO()
        cols = [f for f in AuditEntry.model_fields if f != "details"] + ["details"]
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        for e in entries:
            row = e.model_dump(mode="json")
            row["details"] = json.dumps(row["details"], ensure_ascii=False)
            writer.writerow(row)
        return buf.getvalue()

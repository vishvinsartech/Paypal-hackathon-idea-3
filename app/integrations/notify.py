"""Notifications (spec 9, Zapier): in-app is the alert itself; email/SMS go to a Zapier Catch Hook in sandbox
mode when ZAPIER_CATCH_HOOK_URL is set, otherwise to data/runtime/outbox/ as JSON files ("mocked").

Delivery results per channel: in_app shown|failed; email/sms accepted|failed|mocked. Zapier: 2xx = accepted;
otherwise 3 retries with backoff, then failed (which feeds rule R2's warning check).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.config import Settings
from app.store import atomic_write_text, ts_slug

log = logging.getLogger("subguard.notify")


class Notifier:
    def __init__(self, settings: Settings, outbox_dir: Any, *, client: httpx.AsyncClient | None = None,
                 retry_delays: Sequence[float] = (0.5, 1.0, 2.0)) -> None:
        self.settings = settings
        self.outbox = outbox_dir
        self.client = client
        self.retry_delays = list(retry_delays)
        self.fail_in_app = False  # test hook: simulate the in-app channel failing (corner case 12)

    @property
    def target(self) -> str:
        return "zapier" if self.settings.is_sandbox and self.settings.zapier_catch_hook_url else "outbox"

    def health(self) -> dict[str, str]:
        return {"state": "sandbox" if self.target == "zapier" else "mock", "target": self.target}

    def _write_outbox(self, payload: dict[str, Any], channel: str) -> None:
        name = f"{ts_slug()}-{payload['type']}-{channel}-{payload['idempotency_key'][:40]}.json".replace(":", "_")
        atomic_write_text(self.outbox / name, json.dumps({**payload, "channel": channel}, indent=2))

    async def _post_zapier(self, payload: dict[str, Any]) -> str:
        client = self.client or httpx.AsyncClient(timeout=10)
        try:
            for attempt in range(len(self.retry_delays) + 1):
                try:
                    res = await client.post(self.settings.zapier_catch_hook_url, json=payload)
                    if 200 <= res.status_code < 300:
                        return "accepted"
                except httpx.HTTPError as exc:
                    log.warning(f"zapier post failed: {type(exc).__name__}")
                if attempt < len(self.retry_delays):
                    await asyncio.sleep(self.retry_delays[attempt])
            return "failed"
        finally:
            if self.client is None:
                await client.aclose()

    async def send(self, *, kind: str, to: dict[str, str], subject: str, body: str, idempotency_key: str,
                   channels: Sequence[str], cta_url: str = "") -> dict[str, str]:
        """kind: user_alert | merchant_cancellation. Returns {channel: result} for the external channels."""
        payload = {"type": kind, "to": to, "subject": subject, "body": body, "cta_url": cta_url,
                   "idempotency_key": idempotency_key, "channels": list(channels)}
        if not channels:
            return {}
        if self.target == "zapier":
            result = await self._post_zapier(payload)
            return {ch: result for ch in channels}
        for ch in channels:
            self._write_outbox(payload, ch)
        return {ch: "mocked" for ch in channels}

    def in_app(self) -> str:
        return "failed" if self.fail_in_app else "shown"


def warning_basis(delivery: dict[str, str]) -> tuple[bool, str]:
    """R2: in-app shown + >= 1 Zapier channel accepted, or in-app only if Zapier is mocked or down (logged)."""
    if delivery.get("in_app") != "shown":
        return False, "in_app_failed"
    external = {k: v for k, v in delivery.items() if k != "in_app"}
    if any(v == "accepted" for v in external.values()):
        return True, "zapier_accepted"
    if not external or all(v == "mocked" for v in external.values()):
        return True, "zapier_mocked"
    return True, "zapier_down_in_app_only"

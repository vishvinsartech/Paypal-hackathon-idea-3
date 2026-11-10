"""Milestone 8 check: send ONE test notification through the real Notifier to ZAPIER_CATCH_HOOK_URL.

It uses the same code path as sandbox mode (payload shape, retries with backoff, 2xx = accepted) and prints the
delivery result. Mock mode never calls Zapier: it writes to data/runtime/outbox/ instead.

Usage: python scripts/zapier_check.py [--sms] [--merchant-notice]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.integrations.notify import Notifier  # noqa: E402
from app.store import ts_slug  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sms", action="store_true", help="also ask the Zap for its SMS step")
    ap.add_argument("--merchant-notice", action="store_true", help="send a merchant_cancellation test instead")
    args = ap.parse_args()
    settings = Settings(_env_file=ROOT / ".env", app_mode="sandbox")  # type: ignore[call-arg]
    if not settings.zapier_catch_hook_url:
        print("ZAPIER_CATCH_HOOK_URL is empty in .env: notifications go to data/runtime/outbox/ (mocked).")
        return 1
    host = settings.zapier_catch_hook_url.split("/")[2]
    notifier = Notifier(settings, Path(tempfile.mkdtemp()))
    print(f"Posting a test notification to the Catch Hook on {host} (target: {notifier.target})")
    key = f"zapier-check:{ts_slug()}"
    if args.merchant_notice:
        result = await notifier.send(
            kind="merchant_cancellation", to={"email": "cancel@penwright.example"},
            subject="[SubGuard test] Cancellation notice: subscription I-TEST",
            body="To Penwright Studio support,\n\nThis is a SubGuard test of the written cancellation notice.\n",
            idempotency_key=key, channels=["email"])
    else:
        result = await notifier.send(
            kind="user_alert", to={"email": "usera@subguard-demo.example", "phone": "+15550100001"},
            subject="[SubGuard test] Penwright: I'll cancel it tomorrow",
            body=("Your real deadline is in 2 days. You've opened Penwright twice. "
                  "I'll cancel it tomorrow unless you tap Keep. (SubGuard Zapier test, fictional demo data.)"),
            idempotency_key=key, channels=["email", "sms"] if args.sms else ["email"],
            cta_url="http://127.0.0.1:8000/?user=usera")
    print(f"Delivery: {result}")
    ok = bool(result) and all(v == "accepted" for v in result.values())
    print("Zapier accepted the notification." if ok else "Zapier did NOT accept it (after 3 retries).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

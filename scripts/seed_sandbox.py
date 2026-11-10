"""Seed the PayPal sandbox (`make seed`): products + plans from .env pricing -> data/runtime/sandbox_ids.json.

Usage: python scripts/seed_sandbox.py [--demo-subs] [--no-auto-approve] [--headless]
  --demo-subs        also create one demo Penwright subscription for the buyer
  --no-auto-approve  print the approve links instead of approving them with Playwright
  --headless         run the approval browser headless (default: headed, as PayPal prefers)
Idempotent: re-running reuses every product/plan that still matches the current prices.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.integrations.paypal_rest import PayPalRest  # noqa: E402
from app.integrations.paypal_sdk import SdkPayPal  # noqa: E402
from app.integrations.paypal_seed import Seeder, check_paypal_settings  # noqa: E402
from app.integrations.paypal_types import PayPalError, SubscriptionView  # noqa: E402
from app.store import JsonStore  # noqa: E402

DEMO_SUB_PLANS = ("penwright-pro",)


def sandbox_settings() -> Settings:
    settings = Settings(app_mode="sandbox")  # type: ignore[call-arg]
    problems = check_paypal_settings(settings)
    if problems:
        sys.exit("Can't seed the sandbox: " + " ".join(problems) + " Fill in .env (see .env.example).")
    return settings


async def create_and_approve(sdk: SdkPayPal, plan_ids: list[str], settings: Settings, *, approve: bool,
                             headed: bool, tag: str) -> list[SubscriptionView]:
    """Create one subscription per plan id and (optionally) approve them as the sandbox buyer."""
    from scripts.sandbox_buyer import CANCEL_URL, RETURN_URL, approve_all

    subs = []
    for i, pid in enumerate(plan_ids):
        subs.append(await sdk.create_subscription(pid, request_id=f"subguard-{tag}-{i}-{uuid.uuid4().hex[:12]}",
                                                  return_url=RETURN_URL, cancel_url=CANCEL_URL))
    if not approve:
        for s in subs:
            print(f"  approve {s.id} at {s.approve_url}")
        return subs
    if not (settings.paypal_sandbox_buyer_email and settings.paypal_sandbox_buyer_password):
        sys.exit("PAYPAL_SANDBOX_BUYER_EMAIL / _PASSWORD are needed to auto-approve (or pass --no-auto-approve).")
    oks = await approve_all([s.approve_url or "" for s in subs], settings.paypal_sandbox_buyer_email,
                            settings.paypal_sandbox_buyer_password, headed=headed,
                            shots_dir=settings.runtime_dir / "approve-shots")
    out = []
    for s, ok in zip(subs, oks, strict=True):
        view = s
        for _ in range(20):  # activation can lag the redirect by a few seconds
            view = await sdk.get_subscription(s.id)
            if view.status == "ACTIVE" or not ok:
                break
            await asyncio.sleep(3)
        out.append(view)
    return out


async def main(args: argparse.Namespace) -> int:
    settings = sandbox_settings()
    store = JsonStore(settings.runtime_dir, settings.seed_dir, "sandbox", pricing=settings.pricing)
    rest = PayPalRest(settings)
    sdk = SdkPayPal(settings, rest=rest)
    try:
        items = await Seeder(store, sdk, rest).run()
        for item in items:
            print(f"  {item.kind:7} {item.key:18} {item.paypal_id:28} {item.action}")
        print(f"sandbox ids saved to {store.path('sandbox_ids')}")
        if args.demo_subs:
            ids = store.load("sandbox_ids")
            subs = await create_and_approve(sdk, [ids.plans[k] for k in DEMO_SUB_PLANS], settings,
                                            approve=not args.no_auto_approve, headed=not args.headless,
                                            tag="seed-demo")
            for key, s in zip(DEMO_SUB_PLANS, subs, strict=True):
                ids.demo_subscriptions[key] = s.id
                print(f"  demo sub {key:18} {s.id:20} {s.status}")
            store.save("sandbox_ids", ids)
    except PayPalError as exc:
        print(f"PayPal error: {exc.message} ({exc.summary()}, debug_id={exc.debug_id})", file=sys.stderr)
        return 1
    finally:
        await sdk.aclose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo-subs", action="store_true")
    parser.add_argument("--no-auto-approve", action="store_true")
    parser.add_argument("--headless", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))

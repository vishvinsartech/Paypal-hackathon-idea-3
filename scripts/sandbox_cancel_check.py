"""Milestone 3 sandbox check: a cancel shows CANCELLED via the SDK and via the PayPal MCP server.

Usage: python scripts/sandbox_cancel_check.py [--headless] [--plan framewise-basic]
Creates two subscriptions on a seeded plan, approves both as the sandbox buyer (Playwright), then
cancels #1 through the gateway on the SDK transport and #2 through the gateway on the MCP transport.
Each result is read back over BOTH transports. Every call lands in the audit log. Run `make seed` first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.integrations.paypal_gateway import Ctx, PayPalGateway  # noqa: E402
from app.integrations.paypal_mcp import McpPayPal  # noqa: E402
from app.integrations.paypal_rest import PayPalRest  # noqa: E402
from app.integrations.paypal_sdk import SdkPayPal  # noqa: E402
from app.store import JsonStore  # noqa: E402
from scripts.seed_sandbox import create_and_approve, sandbox_settings  # noqa: E402


async def main(args: argparse.Namespace) -> int:
    settings = sandbox_settings()
    store = JsonStore(settings.runtime_dir, settings.seed_dir, "sandbox", pricing=settings.pricing)
    plan_id = store.load("sandbox_ids").plans.get(args.plan)
    if not plan_id:
        sys.exit(f"No sandbox plan for {args.plan!r}: run `make seed` first.")
    rest = PayPalRest(settings)
    sdk = SdkPayPal(settings, rest=rest)
    mcp = McpPayPal(rest.token)
    sdk_gw = PayPalGateway(settings.model_copy(update={"paypal_transport": "sdk"}), store, sdk=sdk)
    mcp_gw = PayPalGateway(settings.model_copy(update={"paypal_transport": "mcp", "paypal_merchant_mode": "single"}),
                           store, sdk=sdk, mcp=mcp)
    ok = True
    try:
        print("starting PayPal MCP server (npx @paypal/mcp)...")
        if not await mcp.start():
            print(f"FAIL: MCP server unavailable: {mcp.last_error}")
            return 1
        print(f"  MCP connected: {mcp.server_version}, {len(mcp.tools)} tools")
        print(f"creating + approving 2 subscriptions on {args.plan} ({plan_id})...")
        subs = await create_and_approve(sdk, [plan_id, plan_id], settings, approve=True,
                                        headed=not args.headless, tag="m3-check")
        for s in subs:
            print(f"  {s.id}: {s.status}")
        if any(s.status != "ACTIVE" for s in subs):
            print("FAIL: subscriptions did not become ACTIVE (see data/runtime/approve-shots/)")
            return 1
        for label, gw, sub in (("SDK", sdk_gw, subs[0]), ("MCP", mcp_gw, subs[1])):
            ctx = Ctx(actor="system", extra={"reason": f"milestone 3 sandbox check ({label})"})
            out = await gw.cancel(sub.id, f"SubGuard milestone 3 check via {label}", ctx)
            via_sdk = (await sdk.get_subscription(sub.id)).status
            via_mcp = (await mcp.get_subscription(sub.id)).status
            passed = out.ok and out.transport == label.lower() and via_sdk == via_mcp == "CANCELLED"
            ok &= passed
            print(f"  cancel via {label}: ok={out.ok} transport={out.transport} request_id={out.request_id} "
                  f"{out.status_before} -> {out.status_after}; read back SDK={via_sdk} MCP={via_mcp} "
                  f"=> {'PASS' if passed else 'FAIL'}")
        verify = store.audit.verify()
        print(f"audit log chain: {verify}")
    finally:
        await mcp.stop()
        await sdk.aclose()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--plan", default="framewise-basic")
    sys.exit(asyncio.run(main(parser.parse_args())))

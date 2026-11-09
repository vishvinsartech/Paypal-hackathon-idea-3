# PayPal MCP server: tool names

Server: `npx -y @paypal/mcp --tools=all`, env `PAYPAL_ACCESS_TOKEN` (from `scripts/paypal_token.sh`),
`PAYPAL_ENVIRONMENT=SANDBOX`. Remote alternative: `https://mcp.sandbox.paypal.com/http` (OAuth).

**Status: from the docs, not yet confirmed live.** These names come from the official PayPal Agent
Toolkit README (github.com/paypal/agent-toolkit, read 2026-11-10). The local server hasn't been
started yet because it needs sandbox credentials and permission to run `npx` (DECISIONS D-003).
**Milestone 3 must run `session.list_tools()` against the live server**, replace this list with the
exact names and input schemas, and update the "Used by SubGuard" column.

## Used by SubGuard

| Tool | Used for | Fallback |
|---|---|---|
| `show_subscription_details` | `gateway.get_subscription` (single merchant mode) | SDK `get_subscription` |
| `cancel_subscription` | `gateway.cancel` (single merchant mode) | SDK/httpx cancel |
| `list_subscription_plans` | Dev: inspect seeded plans | SDK `list_billing_plans` |
| `show_subscription_plan_details` | Dev: verify `billing_cycles` / price rise | SDK `get_billing_plan` |
| `list_transactions` | Dev: prove no charge happened | SDK transaction search |

Expected input shapes (to be confirmed): `show_subscription_details {id}`,
`cancel_subscription {id, payload: {reason}}`. **Read the real schema before coding.**

## All tools listed in the toolkit README

- **Subscriptions:** `create_subscription_plan`, `list_subscription_plans`, `show_subscription_plan_details`,
  `create_subscription`, `show_subscription_details`, `update_subscription`, `cancel_subscription`
- **Catalog:** `create_product`, `list_products`, `show_product_details`
- **Invoices:** `create_invoice`, `list_invoices`, `get_invoice`, `search_invoicing`, `update_invoicing`,
  `send_invoice`, `send_invoice_reminder`, `cancel_invoice_auto_reminder`, `cancel_sent_invoice`,
  `delete_invoice`, `generate_invoice_qr_code`, `generate_invoice_number`,
  `record_payment_for_invoice`, `record_refund_for_invoice`, `create_conditional_rules_for_invoice`
- **Recurring invoices:** `create_recurring_series`, `activate_recurring_series`, `get_recurring_series`,
  `cancel_recurring_series`, `delete_recurring_series`
- **Payments:** `create_order`, `get_order`, `pay_order`, `create_refund`, `get_refund`
- **Disputes:** `list_disputes`, `get_dispute`, `accept_dispute_claim`
- **Shipment tracking:** `create_shipment_tracking`, `get_shipment_tracking`, `update_shipment_tracking`
- **Reporting:** `list_transactions`, `get_merchant_insights`

Note: the MCP server acts as whoever owns `PAYPAL_ACCESS_TOKEN`, so in `PAYPAL_MERCHANT_MODE=partner`
merchant-side calls go through REST with `PayPal-Auth-Assertion` instead (spec section 4).

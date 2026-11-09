# PayPal MCP server: tool names (verified live)

**Verified 2026-11-10** against the running server: `npx -y @paypal/mcp --tools=all`, which reports
`PayPal 1.11.0`, "Mode: Sandbox", **28 tools**. Env: `PAYPAL_ACCESS_TOKEN` (client-credentials token,
see `scripts/paypal_token.sh`; sandbox tokens expire after a few hours) and `PAYPAL_ENVIRONMENT=SANDBOX`.

Note: the agent-toolkit README lists `update_subscription`, but this server version does **not** expose
it. The live list below wins.

## Used by SubGuard (`app/integrations/paypal_mcp.py`)

| Tool | Arguments (bold = required) | Used for | Fallback |
|---|---|---|---|
| `show_subscription_details` | **subscription_id**, get_additional_details | `gateway.get_subscription` (single-merchant mode) | SDK `get_subscription` |
| `cancel_subscription` | **subscription_id**, **payload** `{reason}` | `gateway.cancel` (single-merchant mode) | SDK `cancel_subscription` |
| `show_subscription_plan_details` | **plan_id** | dev: verify `billing_cycles` / price rise | SDK `get_billing_plan` |
| `list_subscription_plans` | product_id, page, page_size, total_required | dev: inspect seeded plans | SDK `list_billing_plans` |
| `list_transactions` | transaction_id, transaction_status, start_date, end_date, … | dev: show no charge happened | none |

The MCP server acts as whoever owns `PAYPAL_ACCESS_TOKEN`. So in `PAYPAL_MERCHANT_MODE=partner`,
merchant-side calls go through the SDK with `PayPal-Auth-Assertion` instead (spec section 4).

## All 28 tools

| Tool | Arguments (bold = required) |
|---|---|
| `accept_dispute_claim` | **dispute_id**, **note** |
| `cancel_sent_invoice` | **invoice_id**, note, send_to_recipient, additional_recipients |
| `cancel_subscription` | **subscription_id**, **payload** |
| `create_invoice` | **currency_code**, **primary_recipients**, **items**, invoice_number, invoice_date, … (25 fields) |
| `create_order` | **currencyCode**, **items**, discount, shippingCost, shippingAddress, notes, returnUrl, cancelUrl |
| `create_product` | **name**, **type**, description, category, image_url, home_url |
| `create_refund` | **capture_id**, amount, invoice_id, note_to_payer |
| `create_shipment_tracking` | order_id, **tracking_number**, **transaction_id**, status, carrier |
| `create_subscription` | **plan_id**, quantity, shipping_amount, subscriber, application_context |
| `create_subscription_plan` | **product_id**, **name**, description, **billing_cycles**, payment_preferences, taxes |
| `generate_invoice_qr_code` | **invoice_id**, width, height |
| `get_dispute` | **dispute_id** |
| `get_invoice` | **invoice_id** |
| `get_order` | **id** |
| `get_refund` | **refund_id** |
| `get_shipment_tracking` | order_id, transaction_id |
| `list_disputes` | disputed_transaction_id, dispute_state, page_size, page |
| `list_invoices` | page, page_size, total_required |
| `list_products` | page, page_size, total_required |
| `list_subscription_plans` | product_id, page, page_size, total_required |
| `list_transactions` | transaction_id, transaction_status, start_date, end_date, search_months, page_size, page |
| `pay_order` | **id** |
| `send_invoice` | **invoice_id**, note, send_to_recipient, additional_recipients |
| `send_invoice_reminder` | **invoice_id**, subject, note, additional_recipients |
| `show_product_details` | **product_id** |
| `show_subscription_details` | **subscription_id**, get_additional_details |
| `show_subscription_plan_details` | **plan_id** |
| `update_product` | **product_id**, **operations** |

Input patterns worth knowing: `subscription_id` must match `^[A-Za-z0-9_-]{3,50}$`, and `plan_id`
must match `^[A-Za-z0-9_-]{12,32}$`.

#!/usr/bin/env bash
# Prints a PayPal SANDBOX access token (client-credentials) for the PayPal MCP server.
# Usage: export PAYPAL_ACCESS_TOKEN=$(scripts/paypal_token.sh)
# Sandbox tokens expire after a few hours: re-run this and restart the MCP server when they do.
set -euo pipefail

if [ -f .env ]; then set -a; . ./.env; set +a; fi
: "${PAYPAL_CLIENT_ID:?PAYPAL_CLIENT_ID is not set (see .env.example)}"
: "${PAYPAL_CLIENT_SECRET:?PAYPAL_CLIENT_SECRET is not set (see .env.example)}"
BASE="${PAYPAL_API_BASE:-https://api-m.sandbox.paypal.com}"
if [ "$BASE" != "https://api-m.sandbox.paypal.com" ]; then
  echo "Refusing: SubGuard is sandbox only (PAYPAL_API_BASE=$BASE)" >&2; exit 1
fi

curl -sS -u "$PAYPAL_CLIENT_ID:$PAYPAL_CLIENT_SECRET" \
  -d "grant_type=client_credentials" "$BASE/v1/oauth2/token" \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])"

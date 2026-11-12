#!/usr/bin/env bash
# Registers the MCP servers SubGuard uses with Claude Code (same as .mcp.json), then lists them.
# Failures are reported but don't stop the script.
set -u

: "${PAYPAL_ENVIRONMENT:=SANDBOX}"
if [ -z "${PAYPAL_ACCESS_TOKEN:-}" ]; then
  echo "PAYPAL_ACCESS_TOKEN is empty. Run: export PAYPAL_ACCESS_TOKEN=\$(scripts/paypal_token.sh)"
fi

# Required: PayPal MCP server (sandbox)
claude mcp add paypal --scope project \
  -e PAYPAL_ACCESS_TOKEN="${PAYPAL_ACCESS_TOKEN:-}" -e PAYPAL_ENVIRONMENT="$PAYPAL_ENVIRONMENT" \
  -- npx -y @paypal/mcp --tools=all || echo "WARN: could not add paypal MCP"

# Required: APIMatic Context Plugin for PayPal (SDK knowledge for Claude Code)
npx -y context-plugins install paypal || echo "WARN: context plugin install failed (see README)"

# Optional servers
claude mcp add ag-grid --scope user -- npx -y ag-mcp || echo "WARN: ag-mcp unavailable"
claude mcp add --transport http zapier https://mcp.zapier.com/api/mcp/mcp || echo "WARN: zapier MCP not added"
if [ -n "${RENDER_API_KEY:-}" ]; then
  claude mcp add --transport http render https://mcp.render.com/mcp \
    --header "Authorization: Bearer ${RENDER_API_KEY}" || echo "WARN: render MCP not added"
fi

claude mcp list

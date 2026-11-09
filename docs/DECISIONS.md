# Decisions

Ambiguities resolved with the simplest reasonable option. Newest at the bottom.

## Environment

- **D-001 Python 3.14 venv.** The dev machine's default is Python 3.14.4 (3.11 and 3.12 are also
  installed). Every dependency installed cleanly on 3.14. The code targets 3.11+ (no 3.12+-only syntax).
- **D-002 No `make` on Windows.** This machine has no `make`. The `Makefile` is the canonical
  interface (judges on macOS/Linux). `scripts/tasks.py` mirrors every target
  (`python scripts/tasks.py setup|dev|test|...`) so Windows works without installing anything.
- **D-003 External npx tools not run yet.** The APIMatic Context Plugin installer
  (`npx context-plugins install paypal`) and the PayPal MCP server (`npx @paypal/mcp`) weren't
  executed in milestone 1 because the session's permission policy blocked running external npx code,
  and there are no sandbox credentials yet. Workarounds: `PAYPAL_SDK_NOTES.md` was written from the
  installed `paypal-server-sdk` 2.4.0 source (authoritative for that version), and `PAYPAL_TOOLS.md`
  from the official agent-toolkit README. Both must be re-verified at milestone 3.
- **D-004 `claude` CLI.** It isn't on PATH. The binary bundled with the VS Code extension
  (Claude Code 2.1.319) was used for `claude mcp list`. `scripts/mcp_setup.sh` assumes `claude` is on PATH.

## PayPal

- **D-010 httpx for SDK gaps** (spec 5 requires each case to be recorded). `paypal-server-sdk`
  2.4.0 has (a) no Catalog Products controller, (b) no `PayPal-Request-Id` parameter on
  `cancel_subscription` / `update_billing_plan_pricing_schemes`, (c) no per-call custom headers (so
  no `PayPal-Auth-Assertion`), and (d) no webhook signature verification. Those four calls use httpx
  with a token from the same OAuth credentials. Everything else uses the SDK.

## Not used in v1 (sponsor tools)

- **Bryntum:** a CSS timeline is enough for a prototype.
- **Elastic:** about 20 dark-pattern examples fit in a JSON file.
- **KERNEL:** our dummy site is local, so local Playwright is simpler than a cloud browser + tunnel.
- **Postman:** the README + FastAPI's `/docs` are enough.
- **Astropods:** not needed to run or judge the prototype.
- **Channel3:** product search doesn't fit this project.

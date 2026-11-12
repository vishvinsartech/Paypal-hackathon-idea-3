"""The account bits of Priya's dashboard (Phase 7 Step 3): masked email, Connected accounts, Last signed in.

Mode and the Zapier state come from `integration_states`, the same source `/healthz` uses. No secrets, only states.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config import Settings
from app.routes.deps import integration_states
from app.store import JsonStore


def short_email(email: str) -> str:
    """"priya@…": the local part only, the domain hidden (the avatar menu and Profile)."""
    return f"{email.split('@', 1)[0]}@…" if "@" in email else ""


def last_signed_in(store: JsonStore, user: str) -> str | None:
    """The latest `signed_in` audit entry for this user, e.g. "Nov 12, 14:03 UTC"; None if there is none."""
    entries = store.audit.query(user=user, event="signed_in")
    if not entries:
        return None
    try:
        ts = datetime.fromisoformat(entries[-1].ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return f"{ts:%b} {ts.day}, {ts:%H:%M} UTC"


def account_context(settings: Settings, store: JsonStore, user: str, email: str) -> dict[str, Any]:
    states = integration_states(settings)
    return {
        "masked_email": short_email(email),
        "last_signed_in": last_signed_in(store, user),
        "connected": {"paypal_mode": "PayPal Sandbox" if settings.is_sandbox else "Demo data",
                      "zapier": states["notify"]["state"] == "sandbox"},
    }

"""Dashboard APIs (D-174): the three Analytics charts, and Priya's Settings (plain-word consent options)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.services import Services
from app.routes.actions import get_services
from app.routes.dashboard_view import analytics

router = APIRouter(prefix="/api")


@router.get("/dashboard/analytics")
def dashboard_analytics(user: str = "priya", svc: Services = Depends(get_services)) -> dict[str, Any]:
    """R5: only this user's subscriptions and sample history."""
    subs = [s for s in svc.store.load("subscriptions").items if s.owner_id == user and s.status != "APPROVAL_PENDING"]
    return analytics(svc, user, subs)


class SettingsIn(BaseModel):
    user_id: str
    auto_cancel_trials: bool
    auto_send_notice: bool
    remind_by_email: bool


@router.post("/settings")
async def save_settings(body: SettingsIn, svc: Services = Depends(get_services)) -> dict[str, Any]:
    """Maps the plain words to the existing consent options: R2 trial auto-cancel, the D7 auto-send default, and
    the reminder channels (the app is always on; SMS, if set up, is left as it was). Audited."""
    async with svc.store.aedit("users") as users:
        user = next((u for u in users.items if u.id == body.user_id), None)
        if user is None:
            raise HTTPException(404, "Unknown user")
        st = user.settings
        before = st.model_dump()
        st.auto_cancel_trials = body.auto_cancel_trials
        st.auto_send_notice = body.auto_send_notice
        rest = [c for c in st.channels if c not in ("in_app", "email")]
        st.channels = ["in_app", *(["email"] if body.remind_by_email else []), *rest]
        after = st.model_dump()
    svc.store.audit.append(actor="user", event="settings_changed", user_id=body.user_id, decision="n/a",
                           reason="Changed in Settings",
                           details={k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]})
    return {"settings": after}

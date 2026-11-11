"""Cancellation email API (D-104, demo only): list drafts/sent emails, Send (demo outbox), Open in Gmail."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.notices import GMAIL_MAX_URL, EmailIn, FinalizeResult, SentVia, finalize
from app.core.policy import Decision
from app.core.services import Services
from app.models import Notice
from app.routes.actions import blocked, get_services

router = APIRouter(prefix="/api")


class FinalizeIn(EmailIn):
    user_id: str


class NoticeOut(BaseModel):
    notice: Notice
    already_sent: bool = False
    url: str | None = None
    too_long: bool = False
    max_url: int = GMAIL_MAX_URL


@router.get("/notices")
def list_notices(user: str = "priya", svc: Services = Depends(get_services)) -> list[Notice]:
    mine = {s.id for s in svc.store.load("subscriptions").items if s.owner_id == user}
    return [n for n in svc.store.load("notices").items if n.subscription_id in mine]


async def _finalize(svc: Services, notice_id: str, body: FinalizeIn, via: SentVia) -> dict[str, Any] | JSONResponse:
    try:
        out = await finalize(svc, body.user_id, notice_id, EmailIn(to=body.to, subject=body.subject, body=body.body),
                             via)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if isinstance(out, Decision):
        return blocked(out)
    res: FinalizeResult = out
    return NoticeOut(**res.model_dump()).model_dump(mode="json")


@router.post("/notices/{notice_id}/send", response_model=None)
async def send(notice_id: str, body: FinalizeIn,
               svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    """"Send" in the preview: saves the final text to the demo outbox. A second click returns the sent email."""
    return await _finalize(svc, notice_id, body, "demo_outbox")


@router.post("/notices/{notice_id}/gmail", response_model=None)
async def gmail(notice_id: str, body: FinalizeIn,
                svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    """"Open in Gmail": records the edited text and returns the compose link (`too_long` if over the limit)."""
    return await _finalize(svc, notice_id, body, "gmail_compose_link")


@router.post("/notices/{notice_id}/mailto", response_model=None)
async def mailto(notice_id: str, body: FinalizeIn,
                 svc: Services = Depends(get_services)) -> dict[str, Any] | JSONResponse:
    """U13 "Open in my email app": records the edited text; the page opens a mailto: link with it."""
    return await _finalize(svc, notice_id, body, "mailto")

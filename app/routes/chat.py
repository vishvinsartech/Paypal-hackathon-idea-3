"""Chat API: POST /api/chat streams the agent's reply as Server-Sent Events (spec 7.3)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.agent import run_chat
from app.core.services import Services
from app.routes.actions import get_services

router = APIRouter(prefix="/api")
log = logging.getLogger("subguard.chat")


class ChatIn(BaseModel):
    user_id: str
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/chat")
async def chat(body: ChatIn, request: Request, svc: Services = Depends(get_services)) -> StreamingResponse:
    if svc.user(body.user_id) is None:
        raise HTTPException(404, "Unknown user")
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def work() -> None:
        try:
            await run_chat(svc, request.app.state.llm, body.user_id, body.history, body.message, queue.put_nowait)
        except Exception:  # never a stack trace in the UI
            log.exception("chat failed")
            queue.put_nowait({"type": "error", "text": "Something went wrong. Nothing was changed."})
        finally:
            queue.put_nowait(None)

    async def stream() -> AsyncIterator[str]:
        task = asyncio.create_task(work())
        try:
            while (event := await queue.get()) is not None:
                yield sse(event)
        finally:
            await task

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/chat/info")
def chat_info(request: Request) -> dict[str, str]:
    llm = request.app.state.llm
    return {"provider": llm.name, "model": llm.model}

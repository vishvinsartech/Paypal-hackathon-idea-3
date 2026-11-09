"""Demo controls. Milestone 2: reset only (advance / price-rise / toggle arrive in milestone 5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.routes.deps import get_store
from app.store import JsonStore

router = APIRouter(prefix="/api/demo")


@router.post("/reset")
async def reset(store: JsonStore = Depends(get_store)) -> dict[str, object]:
    async with store.alocked():
        store.reset()
        store.audit.append(actor="user", event="demo_control", reason="reset", details={"action": "reset"})
    return {"ok": True, "sim_day": store.load("state").sim_day}

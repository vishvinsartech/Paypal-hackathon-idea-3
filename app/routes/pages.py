"""Server-rendered SubGuard pages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import ROOT_DIR, Settings
from app.routes.deps import get_settings, get_store
from app.store import JsonStore

router = APIRouter()
templates = Jinja2Templates(directory=ROOT_DIR / "app" / "templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request, user: str = "priya", demo: int = 0,
    settings: Settings = Depends(get_settings), store: JsonStore = Depends(get_store),
) -> HTMLResponse:
    users = store.load("users").items
    current = next((u for u in users if u.id == user), users[0] if users else None)
    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "settings": settings, "users": users, "current_user": current,
            "sim_day": store.load("state").sim_day, "demo": bool(demo),
            "merchants": store.load("merchants").items,
        },
    )

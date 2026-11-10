"""GET /api/analytics: the data behind the AG Charts graphs on the live demo and Priya's dashboard (D-108)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.analytics import analytics
from app.core.services import Services
from app.routes.actions import get_services

router = APIRouter(prefix="/api")


@router.get("/analytics")
def get_analytics(user: str = "priya", svc: Services = Depends(get_services)) -> dict[str, Any]:
    return analytics(svc, user)

"""JSON API: health and the audit log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.config import Settings
from app.core.audit_log import AuditEntry, VerifyResult
from app.routes.deps import get_settings, get_store, integration_states
from app.store import JsonStore

router = APIRouter()


@router.get("/healthz")
def healthz(settings: Settings = Depends(get_settings), store: JsonStore = Depends(get_store)) -> dict[str, Any]:
    state = store.load("state")
    chain = store.audit.verify()
    warnings = list(store.warnings)
    if not chain.ok:
        warnings.append(f"audit log chain broken: {chain.reason}")
    return {
        "status": "ok" if not warnings else "degraded",
        "mode": settings.app_mode,
        "sim_day": state.sim_day,
        "integrations": integration_states(settings),
        "audit_chain_ok": chain.ok,
        "warnings": warnings,
    }


@router.get("/api/audit-log")
def audit_log(
    user: str | None = None, event: str | None = None, since_day: int | None = None,
    subscription_id: str | None = None, store: JsonStore = Depends(get_store),
) -> list[AuditEntry]:
    return store.audit.query(user=user, event=event, since_day=since_day, subscription_id=subscription_id)


@router.get("/api/audit-log/verify")
def audit_log_verify(store: JsonStore = Depends(get_store)) -> VerifyResult:
    return store.audit.verify()


@router.get("/api/audit-log.csv")
def audit_log_csv(
    user: str | None = None, event: str | None = None, since_day: int | None = None,
    store: JsonStore = Depends(get_store),
) -> Response:
    csv_text = store.audit.to_csv(store.audit.query(user=user, event=event, since_day=since_day))
    return Response(
        csv_text, media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="subguard-audit-log.csv"'},
    )

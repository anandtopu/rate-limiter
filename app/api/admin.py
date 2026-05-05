from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

import app.api.depends as rate_limit_depends
from app.ai.telemetry import telemetry_hub
from app.api.security import require_admin_key
from app.core.rules import RulesLoadError
from app.observability.metrics import record_rule_reload_metric

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_key)],
)


def get_rules_manager():
    if not rate_limit_depends.rules_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rules manager is not initialized",
        )
    return rate_limit_depends.rules_manager


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, 500))


def audit_metadata(request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else None
    return {
        "actor": request.headers.get("X-Audit-Actor") or "admin",
        "source": request.headers.get("X-Audit-Source") or "admin-api",
        "reason": request.headers.get("X-Audit-Reason"),
        "request_id": getattr(request.state, "request_id", None),
        "client_host": client_host,
    }


@router.get("/rules")
async def get_rules():
    return get_rules_manager().snapshot()


@router.get("/telemetry/persistent")
async def get_persistent_telemetry(limit: int = 100):
    return {
        "summary": telemetry_hub.persistent_summary(),
        **telemetry_hub.persistent_recent(limit=clamp_limit(limit)),
    }


@router.get("/rules/history")
async def get_rule_history():
    return get_rules_manager().history()


@router.post("/rules/validate")
async def validate_rules(payload: dict[str, Any]):
    try:
        config = get_rules_manager().validate_rules(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
        ) from exc

    return {"valid": True, "rules": config.model_dump(mode="json")}


@router.post("/rules/dry-run")
async def dry_run_rules(payload: dict[str, Any]):
    try:
        return get_rules_manager().dry_run(
            payload,
            events=telemetry_hub.recent_events(),
            window_seconds=telemetry_hub.window_seconds,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
        ) from exc


@router.put("/rules")
async def update_rules(payload: dict[str, Any], request: Request):
    try:
        config = get_rules_manager().update_rules(
            payload,
            audit=audit_metadata(request),
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
        ) from exc

    return {
        "updated": True,
        "rules": config.model_dump(mode="json"),
        "loaded_at": get_rules_manager().loaded_at,
        "version": get_rules_manager().current_version(),
    }


@router.post("/rules/rollback/{version}")
async def rollback_rules(version: int, request: Request):
    try:
        config = get_rules_manager().rollback(version, audit=audit_metadata(request))
    except (RulesLoadError, ValidationError) as exc:
        detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=detail,
        ) from exc

    return {
        "rolled_back": True,
        "rolled_back_from": version,
        "rules": config.model_dump(mode="json"),
        "loaded_at": get_rules_manager().loaded_at,
        "version": get_rules_manager().current_version(),
    }


@router.post("/rules/reload")
async def reload_rules(request: Request):
    try:
        get_rules_manager().refresh(audit=audit_metadata(request))
    except (RulesLoadError, ValidationError) as exc:
        record_rule_reload_metric(status="failed")
        detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=detail,
        ) from exc

    record_rule_reload_metric(status="success")
    return {"reloaded": True, **get_rules_manager().snapshot()}

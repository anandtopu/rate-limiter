from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import ValidationError

import app.api.depends as rate_limit_depends
from app.ai.telemetry import telemetry_hub
from app.api.security import configured_admin_keys, require_admin_key
from app.core.rules import RulesApprovalError, RulesLoadError
from app.observability.metrics import record_rule_reload_metric

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_key)],
)

RULE_POLICY_EXAMPLE = {
    "routes": {
        "/api/data": {
            "global_limit": {
                "rate": 2.0,
                "capacity": 5,
                "algorithm": "token_bucket",
                "fail_mode": "open",
                "tier": "free",
                "owner": "api-platform",
                "sensitivity": "public",
                "description": "Default free-tier API data limit.",
            },
            "overrides": {
                "premium_user": {
                    "rate": 10.0,
                    "capacity": 20,
                    "algorithm": "token_bucket",
                    "fail_mode": "open",
                    "tier": "premium",
                    "owner": "api-platform",
                    "sensitivity": "internal",
                }
            },
        }
    }
}
SENSITIVE_RULE_POLICY_EXAMPLE = {
    "routes": {
        "/api/accounts/{account_id}/data": {
            "global_limit": {
                "rate": 0.5,
                "capacity": 3,
                "algorithm": "sliding_window",
                "fail_mode": "closed",
                "tier": "enterprise",
                "owner": "accounts",
                "sensitivity": "sensitive",
                "description": "Account data uses a stricter fail-closed policy.",
            }
        }
    }
}
RULE_EXPORT_EXAMPLE = {
    "kind": "rate-limiter.rules.export",
    "schema_version": 1,
    "exported_at": 1_734_000_000,
    "version": 4,
    "store": "json",
    "rules": RULE_POLICY_EXAMPLE,
}
RULE_BODY_EXAMPLES = {
    "metadata_policy": {
        "summary": "Policy with metadata fields",
        "description": "Shows tier, owner, sensitivity, description, and per-identifier overrides.",
        "value": RULE_POLICY_EXAMPLE,
    },
    "sensitive_policy": {
        "summary": "Sensitive fail-closed route",
        "description": "Sensitive changes are queued for approval before becoming active.",
        "value": SENSITIVE_RULE_POLICY_EXAMPLE,
    },
}
RULE_IMPORT_BODY_EXAMPLES = {
    **RULE_BODY_EXAMPLES,
    "export_envelope": {
        "summary": "Portable export envelope",
        "description": "Payload returned by GET /admin/rules/export.",
        "value": RULE_EXPORT_EXAMPLE,
    },
}
RULE_SNAPSHOT_EXAMPLE = {
    "loaded_at": 1_734_000_100,
    "version": 4,
    "store": "json",
    "rules": RULE_POLICY_EXAMPLE,
}
DRY_RUN_RESPONSE_EXAMPLE = {
    "valid": True,
    "applied": False,
    "events_analyzed": 125,
    "summary": {
        "routes_changed": 1,
        "routes_added": 0,
        "routes_removed": 0,
        "estimated_denials": 12,
        "current_denials": 4,
        "estimated_additional_denials": 8,
    },
    "routes": [
        {
            "route": "/api/accounts/{account_id}/data",
            "change": "changed",
            "capacity_delta": -2,
            "rate_delta": -1.5,
            "fail_mode_changed": True,
            "algorithm_changed": True,
            "override_changes": {"added": [], "removed": [], "changed": []},
            "estimated_denials": 12,
            "current_denials": 4,
        }
    ],
}
PERSISTENT_TELEMETRY_RESPONSE_EXAMPLE = {
    "filters": {"limit": 50, "since": 1_734_000_000.0, "until": 1_734_003_600.0},
    "summary": {
        "enabled": True,
        "persistent_errors": 0,
        "path": "data/telemetry.sqlite3",
        "events": 250,
        "denied": 20,
        "redis_fail_open": 0,
    },
    "enabled": True,
    "events": [
        {
            "id": 250,
            "timestamp": 1_734_003_500.0,
            "route_path": "/api/data",
            "identifier": "api_key:free_user",
            "allowed": False,
            "remaining": 0,
            "capacity": 5,
            "rate": 2.0,
            "retry_after_s": 1,
            "redis_fail_open": False,
        }
    ],
    "analytics": {
        "routes": [
            {
                "route": "/api/data",
                "requests": 180,
                "denied": 20,
                "denied_pct": 11.11,
                "redis_fail_open": 0,
            }
        ],
        "top_offenders": [{"identifier": "api_key:free_user", "denied": 12}],
    },
}
ROLLBACK_RESPONSE_EXAMPLE = {
    "rolled_back": True,
    "rolled_back_from": 1,
    "rules": RULE_POLICY_EXAMPLE,
    "loaded_at": 1_734_000_200,
    "version": 5,
}
UPDATE_RESPONSE_EXAMPLE = {
    "updated": True,
    **RULE_SNAPSHOT_EXAMPLE,
}
IMPORT_RESPONSE_EXAMPLE = {
    "imported": True,
    **RULE_SNAPSHOT_EXAMPLE,
}


def get_rules_manager():
    if not rate_limit_depends.rules_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rules manager is not initialized",
        )
    return rate_limit_depends.rules_manager


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, 500))


def validate_time_range(since: float | None, until: float | None) -> None:
    if since is not None and since < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="since must be a non-negative Unix timestamp",
        )

    if until is not None and until < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="until must be a non-negative Unix timestamp",
        )

    if since is not None and until is not None and since > until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="since must be less than or equal to until",
        )


def audit_metadata(request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else None
    admin_key_name = getattr(request.state, "admin_key_name", None)
    return {
        "actor": request.headers.get("X-Audit-Actor") or admin_key_name or "admin",
        "source": request.headers.get("X-Audit-Source") or "admin-api",
        "reason": request.headers.get("X-Audit-Reason"),
        "request_id": getattr(request.state, "request_id", None),
        "client_host": client_host,
    }


@router.get(
    "/rules",
    summary="Get active rule policy",
    responses={
        200: {
            "description": "Active rate-limit rules and rule-store metadata.",
            "content": {
                "application/json": {"examples": {"active": {"value": RULE_SNAPSHOT_EXAMPLE}}}
            },
        }
    },
)
async def get_rules():
    return get_rules_manager().snapshot()


@router.get(
    "/rules/export",
    summary="Export active rule policy",
    responses={
        200: {
            "description": "Portable rule export envelope for demo restores or sharing.",
            "content": {
                "application/json": {
                    "examples": {"portable_export": {"value": RULE_EXPORT_EXAMPLE}}
                }
            },
        }
    },
)
async def export_rules():
    return get_rules_manager().export_rules()


@router.get("/keys")
async def get_admin_keys(request: Request):
    return {
        "active_key": getattr(request.state, "admin_key_name", None),
        "configured_keys": sorted(configured_admin_keys()),
    }


@router.get(
    "/ai/anomalies",
    summary="Inspect deterministic AI anomaly findings",
)
async def get_ai_anomalies():
    return telemetry_hub.detect_anomalies()


@router.get(
    "/telemetry/persistent",
    summary="Inspect persisted rate-limit telemetry",
    responses={
        200: {
            "description": "Persisted telemetry events and aggregate summaries.",
            "content": {
                "application/json": {
                    "examples": {"time_filtered": {"value": PERSISTENT_TELEMETRY_RESPONSE_EXAMPLE}}
                }
            },
        }
    },
)
async def get_persistent_telemetry(
    limit: int = Query(
        100,
        description="Maximum number of recent persisted events to return.",
        openapi_examples={"recent_50": {"summary": "Recent 50 events", "value": 50}},
    ),
    since: float | None = Query(
        None,
        description="Inclusive Unix timestamp lower bound for telemetry filters.",
        openapi_examples={
            "demo_start": {"summary": "Demo start timestamp", "value": 1_734_000_000.0}
        },
    ),
    until: float | None = Query(
        None,
        description="Inclusive Unix timestamp upper bound for telemetry filters.",
        openapi_examples={
            "demo_end": {"summary": "Demo end timestamp", "value": 1_734_003_600.0}
        },
    ),
):
    validate_time_range(since=since, until=until)
    clamped_limit = clamp_limit(limit)
    return {
        "filters": {
            "limit": clamped_limit,
            "since": since,
            "until": until,
        },
        "summary": telemetry_hub.persistent_summary(since=since, until=until),
        **telemetry_hub.persistent_recent(
            limit=clamped_limit,
            since=since,
            until=until,
        ),
    }


@router.get("/rules/history")
async def get_rule_history():
    return get_rules_manager().history()


@router.get("/rules/audit")
async def get_rule_audit(
    route: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    sensitivity: str | None = None,
    since: float | None = None,
    until: float | None = None,
    limit: int = 100,
):
    validate_time_range(since=since, until=until)
    return get_rules_manager().audit_log(
        route=route,
        actor=actor,
        action=action,
        sensitivity=sensitivity,
        since=since,
        until=until,
        limit=clamp_limit(limit),
    )


@router.get("/rules/pending")
async def get_pending_rule_updates(include_resolved: bool = False):
    return get_rules_manager().pending_updates(include_resolved=include_resolved)


@router.post(
    "/rules/validate",
    summary="Validate a rule policy without applying it",
)
async def validate_rules(payload: dict[str, Any] = Body(openapi_examples=RULE_BODY_EXAMPLES)):
    try:
        config = get_rules_manager().validate_rules(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
        ) from exc

    return {"valid": True, "rules": config.model_dump(mode="json")}


@router.post(
    "/rules/dry-run",
    summary="Estimate rule policy impact without applying it",
    responses={
        200: {
            "description": "Dry-run impact report based on recent in-memory telemetry.",
            "content": {
                "application/json": {
                    "examples": {"sensitive_tightening": {"value": DRY_RUN_RESPONSE_EXAMPLE}}
                }
            },
        }
    },
)
async def dry_run_rules(payload: dict[str, Any] = Body(openapi_examples=RULE_BODY_EXAMPLES)):
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


@router.post("/rules/recommendation-draft")
async def draft_rules_from_recommendations():
    recommendations = telemetry_hub.generate_recommendations()
    draft = get_rules_manager().draft_from_recommendations(recommendations)
    return {
        **draft,
        "dry_run": get_rules_manager().dry_run(
            draft["rules"],
            events=telemetry_hub.recent_events(),
            window_seconds=telemetry_hub.window_seconds,
        ),
    }


@router.put(
    "/rules",
    summary="Apply or request approval for a rule policy",
    responses={
        200: {
            "description": "Rule policy applied immediately.",
            "content": {
                "application/json": {"examples": {"applied": {"value": UPDATE_RESPONSE_EXAMPLE}}}
            },
        },
        202: {
            "description": "Sensitive rule policy queued for approval.",
            "content": {
                "application/json": {
                    "examples": {
                        "pending_sensitive": {
                            "value": {
                                "updated": False,
                                "pending_approval": True,
                                "approval_id": "approval_123",
                                "base_version": 4,
                                "sensitive_routes": ["/api/accounts/{account_id}/data"],
                                "rules": SENSITIVE_RULE_POLICY_EXAMPLE,
                                "loaded_at": 1_734_000_100,
                                "version": 4,
                                "store": "json",
                            }
                        }
                    }
                }
            },
        },
    },
)
async def update_rules(
    request: Request,
    response: Response,
    payload: dict[str, Any] = Body(openapi_examples=RULE_BODY_EXAMPLES),
):
    manager = get_rules_manager()
    try:
        config = manager.validate_rules(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
        ) from exc

    audit = audit_metadata(request)
    sensitive_routes = manager.sensitive_routes_touched(config)
    if sensitive_routes:
        pending = manager.request_sensitive_update(
            config,
            sensitive_routes=sensitive_routes,
            audit=audit,
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "updated": False,
            "pending_approval": True,
            "approval_id": pending["id"],
            "base_version": pending["base_version"],
            "sensitive_routes": pending["sensitive_routes"],
            "rules": pending["rules"],
            "loaded_at": manager.loaded_at,
            "version": manager.current_version(),
            "store": manager.store.backend,
        }

    config = manager.apply_rules(config, action="update", audit=audit)
    return {
        "updated": True,
        "rules": config.model_dump(mode="json"),
        "loaded_at": manager.loaded_at,
        "version": manager.current_version(),
        "store": manager.store.backend,
    }


@router.post(
    "/rules/import",
    summary="Import a raw or exported rule policy",
    responses={
        200: {
            "description": "Imported rule policy applied immediately.",
            "content": {
                "application/json": {"examples": {"imported": {"value": IMPORT_RESPONSE_EXAMPLE}}}
            },
        },
        202: {
            "description": "Imported sensitive rule policy queued for approval.",
            "content": {
                "application/json": {
                    "examples": {
                        "pending_sensitive_import": {
                            "value": {
                                "imported": False,
                                "pending_approval": True,
                                "approval_id": "approval_123",
                                "base_version": 4,
                                "sensitive_routes": ["/api/accounts/{account_id}/data"],
                                "rules": SENSITIVE_RULE_POLICY_EXAMPLE,
                                "loaded_at": 1_734_000_100,
                                "version": 4,
                                "store": "json",
                            }
                        }
                    }
                }
            },
        },
    },
)
async def import_rules(
    request: Request,
    response: Response,
    payload: dict[str, Any] = Body(openapi_examples=RULE_IMPORT_BODY_EXAMPLES),
):
    manager = get_rules_manager()
    try:
        rules_payload = manager.import_payload_rules(payload)
        config = manager.validate_rules(rules_payload)
    except (RulesLoadError, ValidationError) as exc:
        detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=detail,
        ) from exc

    audit = audit_metadata(request)
    sensitive_routes = manager.sensitive_routes_touched(config)
    if sensitive_routes:
        pending = manager.request_sensitive_update(
            config,
            sensitive_routes=sensitive_routes,
            audit=audit,
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "imported": False,
            "pending_approval": True,
            "approval_id": pending["id"],
            "base_version": pending["base_version"],
            "sensitive_routes": pending["sensitive_routes"],
            "rules": pending["rules"],
            "loaded_at": manager.loaded_at,
            "version": manager.current_version(),
            "store": manager.store.backend,
        }

    config = manager.apply_rules(config, action="import", audit=audit)
    return {
        "imported": True,
        "rules": config.model_dump(mode="json"),
        "loaded_at": manager.loaded_at,
        "version": manager.current_version(),
        "store": manager.store.backend,
    }


@router.post("/rules/pending/{approval_id}/approve")
async def approve_pending_rule_update(approval_id: str, request: Request):
    try:
        config, pending = get_rules_manager().approve_pending_update(
            approval_id,
            audit=audit_metadata(request),
        )
    except (RulesApprovalError, ValidationError) as exc:
        detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from exc

    return {
        "approved": True,
        "approval_id": pending["id"],
        "rules": config.model_dump(mode="json"),
        "loaded_at": get_rules_manager().loaded_at,
        "version": get_rules_manager().current_version(),
    }


@router.post("/rules/pending/{approval_id}/reject")
async def reject_pending_rule_update(approval_id: str, request: Request):
    try:
        pending = get_rules_manager().reject_pending_update(
            approval_id,
            audit=audit_metadata(request),
        )
    except RulesApprovalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return {
        "rejected": True,
        "approval_id": pending["id"],
        "loaded_at": get_rules_manager().loaded_at,
        "version": get_rules_manager().current_version(),
    }


@router.post(
    "/rules/rollback/{version}",
    summary="Restore a previous rule-policy version",
    responses={
        200: {
            "description": "Rollback applied and recorded in rule history.",
            "content": {
                "application/json": {
                    "examples": {"restore_initial": {"value": ROLLBACK_RESPONSE_EXAMPLE}}
                }
            },
        }
    },
)
async def rollback_rules(
    request: Request,
    version: int = Path(
        description="Rule-history version to restore.",
        openapi_examples={"initial": {"summary": "Restore version 1", "value": 1}},
    ),
):
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

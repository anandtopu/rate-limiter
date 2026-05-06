from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path as FilePath
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

import app.api.depends as rate_limit_depends
from app.ai.copilot import (
    SAFETY_CONSTRAINTS,
    CopilotConfigurationError,
    CopilotProviderError,
    PolicyCopilotRequest,
    build_copilot_input,
    get_policy_copilot_adapter,
)
from app.ai.telemetry import telemetry_hub
from app.api.security import configured_admin_keys, require_admin_key
from app.config import settings
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
POLICY_COPILOT_BODY_EXAMPLES = {
    "explain_only": {
        "summary": "Explain current AI signals",
        "description": "Returns an explanation without proposing rule JSON.",
        "value": {"prompt": "Explain recent rate-limit pressure and safest next steps."},
    },
    "validate_draft": {
        "summary": "Validate and dry-run generated policy JSON",
        "description": "The fake adapter treats proposed_rules as generated policy JSON.",
        "value": {
            "prompt": "Review this draft policy and estimate impact before apply.",
            "proposed_rules": RULE_POLICY_EXAMPLE,
        },
    },
}
AI_RESEARCH_REPORT_RESPONSE_EXAMPLE = {
    "schema_version": 1,
    "path": "docs/AI_RESEARCH_REPORT.md",
    "exists": True,
    "bytes": 1200,
    "modified_at": 1_734_000_000.0,
    "etag": 'W/"18e6ec3e2a7c0000-4b0"',
    "last_modified": "Wed, 11 Dec 2024 16:00:00 GMT",
    "line_count": 42,
    "content_type": "text/markdown",
    "download_url": "/admin/ai/research-report?format=markdown&download=true",
    "content": "# AI Rate Limiter Research Report\n\n## Summary\n\n- Overall status: `stable`\n",
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


def research_report_freshness_headers(report_path: FilePath) -> dict[str, str]:
    stat = report_path.stat()
    etag = f'W/"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    return {
        "ETag": etag,
        "Last-Modified": formatdate(stat.st_mtime, usegmt=True),
        "Cache-Control": "no-cache",
    }


def research_report_not_modified(request: Request, report_path: FilePath, etag: str) -> bool:
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        requested_etags = [item.strip() for item in if_none_match.split(",")]
        normalized_etag = etag.removeprefix("W/")
        return "*" in requested_etags or any(
            item.removeprefix("W/") == normalized_etag for item in requested_etags
        )

    if_modified_since = request.headers.get("if-modified-since")
    if not if_modified_since:
        return False

    try:
        modified_since = parsedate_to_datetime(if_modified_since)
    except (TypeError, ValueError, IndexError, OverflowError):
        return False

    return int(report_path.stat().st_mtime) <= int(modified_since.timestamp())


@router.get(
    "/ai/research-report",
    summary="Read the latest generated AI research report artifact",
    responses={
        200: {
            "description": "Configured Markdown AI research report artifact.",
            "content": {
                "application/json": {
                    "examples": {
                        "generated_report": {"value": AI_RESEARCH_REPORT_RESPONSE_EXAMPLE}
                    }
                }
            },
        },
        304: {"description": "Research report artifact has not changed."},
        404: {"description": "Configured AI research report artifact was not found."},
    },
)
async def get_ai_research_report(
    request: Request,
    response: Response,
    format: Literal["json", "markdown"] = Query(
        "json",
        description="Return JSON metadata plus content, or raw Markdown content.",
        openapi_examples={
            "json_view": {"summary": "JSON view", "value": "json"},
            "markdown_view": {"summary": "Markdown view", "value": "markdown"},
        },
    ),
    download: bool = Query(
        False,
        description="When format=markdown, send Content-Disposition as an attachment.",
        openapi_examples={"download_file": {"summary": "Download file", "value": True}},
    ),
):
    configured_path = settings.ai_research_report_path
    report_path = FilePath(configured_path)
    if not report_path.is_absolute():
        report_path = FilePath.cwd() / report_path

    if not report_path.exists() or not report_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI research report artifact not found: {configured_path}",
        )

    stat = report_path.stat()
    freshness_headers = research_report_freshness_headers(report_path)
    if research_report_not_modified(request, report_path, freshness_headers["ETag"]):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=freshness_headers)

    try:
        content = report_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="AI research report artifact must be UTF-8 Markdown",
        ) from exc

    if format == "markdown":
        disposition = "attachment" if download else "inline"
        filename = report_path.name or "AI_RESEARCH_REPORT.md"
        return PlainTextResponse(
            content,
            media_type="text/markdown; charset=utf-8",
            headers={
                **freshness_headers,
                "Content-Disposition": f'{disposition}; filename="{filename}"',
            },
        )

    response.headers.update(freshness_headers)
    return {
        "schema_version": 1,
        "path": configured_path,
        "exists": True,
        "bytes": stat.st_size,
        "modified_at": stat.st_mtime,
        "etag": freshness_headers["ETag"],
        "last_modified": freshness_headers["Last-Modified"],
        "line_count": len(content.splitlines()),
        "content_type": "text/markdown",
        "download_url": "/admin/ai/research-report?format=markdown&download=true",
        "content": content,
    }


@router.post(
    "/ai/policy-copilot",
    summary="Explain telemetry and validate optional AI-generated rule drafts",
)
async def policy_copilot(
    payload: PolicyCopilotRequest = Body(openapi_examples=POLICY_COPILOT_BODY_EXAMPLES),
):
    manager = get_rules_manager()
    try:
        adapter = get_policy_copilot_adapter(
            enabled=settings.ai_copilot_enabled,
            provider=settings.ai_copilot_provider,
            proposed_rules=payload.proposed_rules,
            endpoint=settings.ai_copilot_endpoint,
            api_key=settings.ai_copilot_api_key,
            model=settings.ai_copilot_model,
            timeout_s=settings.ai_copilot_timeout_s,
        )
    except CopilotConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    recommendations = telemetry_hub.generate_recommendations()
    anomalies = telemetry_hub.detect_anomalies()
    copilot_input = build_copilot_input(
        payload,
        active_rules=manager.snapshot()["rules"],
        feature_summary=recommendations.get("feature_summary", {}),
        recommendations=recommendations,
        anomalies=anomalies,
    )
    try:
        result = adapter.generate(copilot_input)
    except CopilotProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    validation: dict[str, Any] = {
        "valid": None,
        "status": "skipped",
        "errors": [],
        "sensitive_routes": [],
    }
    dry_run = None
    if result.proposed_rules is not None:
        try:
            config = manager.validate_rules(result.proposed_rules)
            validation = {
                "valid": True,
                "status": "valid",
                "errors": [],
                "sensitive_routes": manager.sensitive_routes_touched(config),
            }
            dry_run = manager.dry_run(
                result.proposed_rules,
                events=telemetry_hub.recent_events(),
                window_seconds=telemetry_hub.window_seconds,
            )
        except ValidationError as exc:
            validation = {
                "valid": False,
                "status": "invalid",
                "errors": exc.errors(),
                "sensitive_routes": [],
            }

    return {
        "schema_version": 1,
        "enabled": True,
        "provider": adapter.provider,
        "applied": False,
        "explanation": result.explanation,
        "warnings": result.warnings,
        "safety_constraints": SAFETY_CONSTRAINTS,
        "context": {
            "active_routes": len(copilot_input.active_rules.get("routes", {})),
            "events_analyzed": copilot_input.feature_summary.get("events_analyzed", 0),
            "recommendations": len(recommendations.get("items", [])),
            "anomalies": anomalies.get("count", 0),
        },
        "proposed_rules": result.proposed_rules,
        "validation": validation,
        "dry_run": dry_run,
    }


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

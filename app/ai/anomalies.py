import re
from collections import defaultdict
from typing import Any

from app.ai.features import build_feature_summary


def _field(event: Any, name: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


def _finding_id(finding_type: str, route: str | None = None, identifier: str | None = None) -> str:
    raw_key = "_".join(value for value in [route, identifier] if value)
    key = re.sub(r"[^a-zA-Z0-9]+", "_", raw_key).strip("_").lower() or "global"
    return f"anom_{finding_type}_{key}"


def _finding(
    *,
    finding_type: str,
    severity: str,
    rationale: str,
    evidence: dict[str, Any],
    suggested_actions: list[str],
    route: str | None = None,
    identifier: str | None = None,
) -> dict[str, Any]:
    return {
        "id": _finding_id(finding_type, route, identifier),
        "type": finding_type,
        "severity": severity,
        "route": route,
        "identifier": identifier,
        "rationale": rationale,
        "evidence": evidence,
        "suggested_actions": suggested_actions,
    }


def detect_route_spikes(feature_summary: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for route in feature_summary.get("routes", []):
        requests = int(route.get("requests") or 0)
        unique_identifiers = int(route.get("unique_identifiers") or 0)
        if requests < 50 or unique_identifiers < 5:
            continue

        findings.append(_finding(
            finding_type="route_traffic_spike",
            severity="medium" if requests < 100 else "high",
            route=route["route"],
            rationale=(
                "Route traffic volume is high across multiple identifiers in the current "
                "telemetry window."
            ),
            evidence={
                "requests": requests,
                "unique_identifiers": unique_identifiers,
                "denial_ratio": route.get("denial_ratio", 0),
            },
            suggested_actions=[
                "Compare against expected launch, batch, or incident traffic.",
                "Check whether rate-limit pressure is isolated to known clients.",
                "Use dry-run before changing route-wide limits.",
            ],
        ))

    return findings


def detect_concentrated_offenders(feature_summary: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for pair in feature_summary.get("route_identifiers", []):
        requests = int(pair.get("requests") or 0)
        denied = int(pair.get("denied") or 0)
        denial_ratio = float(pair.get("denial_ratio") or 0)
        if requests < 5 or denied < 3 or denial_ratio < 0.5:
            continue

        findings.append(_finding(
            finding_type="concentrated_offender",
            severity="high" if denied >= 10 else "medium",
            route=pair["route"],
            identifier=pair["identifier"],
            rationale=(
                "One identifier accounts for repeated denials on a single route, which "
                "suggests noisy client behavior or abuse."
            ),
            evidence={
                "requests": requests,
                "denied": denied,
                "denial_ratio": denial_ratio,
                "redis_fail_open": pair.get("redis_fail_open", 0),
            },
            suggested_actions=[
                "Inspect client retry behavior.",
                "Consider an identifier-specific override for known clients.",
                "Escalate to upstream abuse controls for unknown or distributed clients.",
            ],
        ))

    return findings


def detect_retry_loops(events: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for event in events:
        route = str(_field(event, "route_path", "unknown"))
        identifier = str(_field(event, "identifier", "unknown"))
        grouped[(route, identifier)].append(event)

    findings = []
    for (route, identifier), pair_events in grouped.items():
        denied_events = sorted(
            [event for event in pair_events if not bool(_field(event, "allowed", False))],
            key=lambda event: float(_field(event, "timestamp", 0)),
        )
        if len(denied_events) < 3:
            continue

        gaps = [
            float(_field(current, "timestamp", 0)) - float(_field(previous, "timestamp", 0))
            for previous, current in zip(denied_events, denied_events[1:], strict=False)
        ]
        retry_after_values = [
            int(value)
            for event in denied_events
            if (value := _field(event, "retry_after_s")) is not None
        ]
        max_expected_gap = max(retry_after_values or [1])
        fast_retries = [gap for gap in gaps if gap <= max_expected_gap]
        if len(fast_retries) < 2:
            continue

        findings.append(_finding(
            finding_type="retry_loop",
            severity="high" if len(denied_events) >= 6 else "medium",
            route=route,
            identifier=identifier,
            rationale=(
                "The same identifier kept retrying quickly after rate-limit denials, "
                "which can amplify load and denial rates."
            ),
            evidence={
                "denied": len(denied_events),
                "fast_retry_gaps": [round(gap, 3) for gap in fast_retries],
                "max_retry_after_s": max_expected_gap,
            },
            suggested_actions=[
                "Check whether the client honors Retry-After.",
                "Add client guidance or SDK backoff.",
                "Consider stricter identifier overrides for repeated retry loops.",
            ],
        ))

    return findings


def detect_sensitive_route_probing(feature_summary: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for route in feature_summary.get("routes", []):
        sensitivities = set(route.get("sensitivities") or [])
        if "sensitive" not in sensitivities:
            continue
        requests = int(route.get("requests") or 0)
        unique_identifiers = int(route.get("unique_identifiers") or 0)
        denied = int(route.get("denied") or 0)
        if requests < 3 or (unique_identifiers < 3 and denied < 2):
            continue

        findings.append(_finding(
            finding_type="sensitive_route_probing",
            severity="high",
            route=route["route"],
            rationale=(
                "Sensitive route traffic is spread across several identifiers or causing "
                "denials, which can indicate probing."
            ),
            evidence={
                "requests": requests,
                "unique_identifiers": unique_identifiers,
                "denied": denied,
                "sensitivities": sorted(sensitivities),
            },
            suggested_actions=[
                "Review authentication and access logs for this route.",
                "Prefer fail-closed behavior for sensitive endpoints.",
                "Consider tighter per-identifier controls if probing continues.",
            ],
        ))

    return findings


def detect_redis_outage_exposure(feature_summary: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for route in feature_summary.get("routes", []):
        redis_fail_open = int(route.get("redis_fail_open") or 0)
        if redis_fail_open <= 0:
            continue

        severity = "high" if "sensitive" in set(route.get("sensitivities") or []) else "medium"
        findings.append(_finding(
            finding_type="redis_outage_exposure",
            severity=severity,
            route=route["route"],
            rationale=(
                "Requests were allowed while Redis was unavailable, so limiter protection "
                "was bypassed for this route."
            ),
            evidence={
                "redis_fail_open": redis_fail_open,
                "sensitivities": route.get("sensitivities", []),
                "fail_modes": route.get("fail_modes", []),
            },
            suggested_actions=[
                "Investigate Redis health and connection limits.",
                "Add alerting for Redis fail-open counters.",
                "Consider fail-closed for sensitive routes.",
            ],
        ))

    return findings


def detect_anomalies(events: list[Any], *, generated_at: int) -> dict[str, Any]:
    event_list = list(events)
    feature_summary = build_feature_summary(event_list)
    findings = [
        *detect_route_spikes(feature_summary),
        *detect_concentrated_offenders(feature_summary),
        *detect_retry_loops(event_list),
        *detect_sensitive_route_probing(feature_summary),
        *detect_redis_outage_exposure(feature_summary),
    ]
    findings = sorted(
        findings,
        key=lambda item: (item["type"], item.get("route") or "", item["id"]),
    )
    return {
        "generated_at": generated_at,
        "schema_version": 1,
        "events_analyzed": len(event_list),
        "count": len(findings),
        "findings": findings,
    }

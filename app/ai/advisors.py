import re
from typing import Any

from app.ai.features import build_feature_summary


def _recommendation_id(recommendation_type: str, route: str, suffix: str = "") -> str:
    route_key = re.sub(r"[^a-zA-Z0-9]+", "_", route).strip("_").lower() or "global"
    suffix_key = f"_{suffix}" if suffix else ""
    return f"rec_{recommendation_type}_{route_key}{suffix_key}"


def _severity_for_ratio(ratio: float) -> str:
    if ratio >= 0.3:
        return "high"
    if ratio >= 0.15:
        return "medium"
    return "low"


def _confidence(sample_size: int, signal_strength: float) -> float:
    sample_factor = min(1.0, sample_size / 100)
    return round(max(0.1, min(0.95, 0.35 + sample_factor * 0.35 + signal_strength * 0.25)), 2)


def _legacy_recommendation(
    *,
    action: str,
    message: str,
    suggested_next_steps: list[str],
) -> dict[str, Any]:
    return {
        "action": action,
        "message": message,
        "suggested_next_steps": suggested_next_steps,
    }


def tuning_advisor(feature_summary: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations = []
    for route in feature_summary.get("routes", []):
        requests = int(route.get("requests") or 0)
        denied = int(route.get("denied") or 0)
        denial_ratio = float(route.get("denial_ratio") or 0)
        if requests < 20 or denial_ratio < 0.15:
            continue

        multiplier = 2.0 if denial_ratio >= 0.3 else 1.5
        severity = _severity_for_ratio(denial_ratio)
        message = (
            "High 429 ratio suggests this route may be under-provisioned for observed "
            "traffic or clients are retrying too aggressively."
        )
        recommendations.append({
            "id": _recommendation_id("tuning", route["route"]),
            "type": "tuning",
            "route": route["route"],
            "severity": severity,
            "confidence": _confidence(requests, denial_ratio),
            "signals": {
                "requests": requests,
                "rate_limited": denied,
                "rate_limited_ratio": denial_ratio,
                "unique_identifiers": route.get("unique_identifiers", 0),
            },
            "signal": {
                "requests": requests,
                "rate_limited": denied,
                "rate_limited_ratio": denial_ratio,
            },
            "rationale": message,
            "proposed_change": {
                "kind": "scale_route_limit",
                "route": route["route"],
                "rate_multiplier": multiplier,
                "capacity_multiplier": multiplier,
                "min_capacity_increment": 1,
            },
            "expected_impact": {
                "direction": "reduce_denials",
                "estimated_affected_requests": denied,
                "risk": "May allow more burst traffic from all identifiers on the route.",
            },
            "safety_notes": [
                "Validate and dry-run before applying.",
                "If one identifier dominates denials, prefer an abuse-specific override.",
            ],
            "recommendation": _legacy_recommendation(
                action="review_limits",
                message=message,
                suggested_next_steps=[
                    "Check whether traffic is legitimate or caused by retry loops.",
                    "If legitimate, consider increasing capacity or sustained rate.",
                    "If abusive, add identifier-specific overrides instead.",
                ],
            ),
        })

    return recommendations


def abuse_advisor(feature_summary: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations = []
    for pair in feature_summary.get("route_identifiers", []):
        requests = int(pair.get("requests") or 0)
        denied = int(pair.get("denied") or 0)
        denial_ratio = float(pair.get("denial_ratio") or 0)
        if requests < 5 or denied < 3 or denial_ratio < 0.5:
            continue

        message = (
            "A single identifier is responsible for repeated denials on this route, "
            "which is a stronger abuse signal than route-level pressure alone."
        )
        recommendations.append({
            "id": _recommendation_id("abuse", pair["route"], pair["identifier"]),
            "type": "abuse",
            "route": pair["route"],
            "severity": "high" if denied >= 10 else "medium",
            "confidence": _confidence(requests, denial_ratio),
            "signals": {
                "identifier": pair["identifier"],
                "requests": requests,
                "rate_limited": denied,
                "rate_limited_ratio": denial_ratio,
            },
            "signal": {
                "identifier": pair["identifier"],
                "requests": requests,
                "rate_limited": denied,
                "rate_limited_ratio": denial_ratio,
            },
            "rationale": message,
            "proposed_change": {
                "kind": "add_identifier_override",
                "route": pair["route"],
                "identifier": pair["identifier"],
                "rate_multiplier": 0.5,
                "capacity_multiplier": 0.5,
            },
            "expected_impact": {
                "direction": "contain_noisy_identifier",
                "estimated_affected_requests": requests,
                "risk": "Exact identifier overrides are best for known clients, not broad abuse.",
            },
            "safety_notes": [
                "Review whether the identifier is a legitimate premium client.",
                "Prefer upstream abuse controls for distributed attacks.",
            ],
            "recommendation": _legacy_recommendation(
                action="review_identifier_override",
                message=message,
                suggested_next_steps=[
                    "Inspect the client behavior and retry pattern.",
                    "Consider an identifier-specific override for known abusive clients.",
                    "For unknown or distributed abuse, use upstream WAF or auth controls.",
                ],
            ),
        })

    return recommendations


def reliability_advisor(feature_summary: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations = []
    for route in feature_summary.get("routes", []):
        redis_fail_open = int(route.get("redis_fail_open") or 0)
        sensitivities = set(route.get("sensitivities") or [])
        fail_modes = set(route.get("fail_modes") or [])
        if redis_fail_open <= 0 or "sensitive" not in sensitivities or "open" not in fail_modes:
            continue

        message = (
            "Sensitive route traffic was allowed during Redis failure while configured "
            "fail-open. This can bypass protection during limiter outages."
        )
        recommendations.append({
            "id": _recommendation_id("reliability", route["route"]),
            "type": "reliability",
            "route": route["route"],
            "severity": "high",
            "confidence": _confidence(int(route.get("requests") or 0), 1.0),
            "signals": {
                "redis_fail_open": redis_fail_open,
                "sensitivities": sorted(sensitivities),
                "fail_modes": sorted(fail_modes),
            },
            "signal": {"redis_fail_open_total": redis_fail_open},
            "rationale": message,
            "proposed_change": {
                "kind": "set_fail_mode",
                "route": route["route"],
                "fail_mode": "closed",
            },
            "expected_impact": {
                "direction": "reduce_outage_bypass",
                "estimated_affected_requests": redis_fail_open,
                "risk": "Redis outages will deny traffic for this sensitive route.",
            },
            "safety_notes": [
                "Sensitive fail-mode changes require approval.",
                "Confirm availability tradeoff with the route owner.",
            ],
            "recommendation": _legacy_recommendation(
                action="investigate_redis",
                message=message,
                suggested_next_steps=[
                    "Check Redis health and fail-open counters.",
                    "Consider fail-closed for sensitive routes.",
                    "Add alerting on Redis fail-open events.",
                ],
            ),
        })

    return recommendations


def algorithm_advisor(feature_summary: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations = []
    for route in feature_summary.get("routes", []):
        requests = int(route.get("requests") or 0)
        denial_ratio = float(route.get("denial_ratio") or 0)
        algorithms = set(route.get("algorithms") or [])
        concentration = float(route.get("top_identifier_concentration") or 0)
        if requests < 20 or denial_ratio < 0.15 or "fixed_window" not in algorithms:
            continue
        if concentration >= 0.8:
            continue

        message = (
            "This fixed-window route has broad denial pressure. Sliding window can "
            "smooth boundary bursts while preserving a hard rolling limit."
        )
        recommendations.append({
            "id": _recommendation_id("algorithm", route["route"]),
            "type": "algorithm",
            "route": route["route"],
            "severity": _severity_for_ratio(denial_ratio),
            "confidence": _confidence(requests, denial_ratio),
            "signals": {
                "requests": requests,
                "rate_limited_ratio": denial_ratio,
                "algorithm": "fixed_window",
                "top_identifier_concentration": concentration,
            },
            "signal": {
                "requests": requests,
                "rate_limited_ratio": denial_ratio,
                "algorithm": "fixed_window",
            },
            "rationale": message,
            "proposed_change": {
                "kind": "set_algorithm",
                "route": route["route"],
                "algorithm": "sliding_window",
            },
            "expected_impact": {
                "direction": "smooth_window_boundaries",
                "estimated_affected_requests": int(route.get("denied") or 0),
                "risk": "May alter client-visible reset timing and remaining counts.",
            },
            "safety_notes": [
                "Dry-run and load-test before applying algorithm changes.",
                "Confirm clients do not depend on fixed-window reset behavior.",
            ],
            "recommendation": _legacy_recommendation(
                action="review_algorithm",
                message=message,
                suggested_next_steps=[
                    "Compare fixed-window and sliding-window behavior in dry-run.",
                    "Check if denials cluster around window boundaries.",
                    "Load-test representative clients before applying.",
                ],
            ),
        })

    return recommendations


def generate_advisor_recommendations(events: list[Any], *, generated_at: int) -> dict[str, Any]:
    feature_summary = build_feature_summary(events)
    items = [
        *tuning_advisor(feature_summary),
        *abuse_advisor(feature_summary),
        *reliability_advisor(feature_summary),
        *algorithm_advisor(feature_summary),
    ]
    items = sorted(items, key=lambda item: (item["type"], item["route"], item["id"]))
    return {
        "generated_at": generated_at,
        "schema_version": 2,
        "feature_summary": feature_summary,
        "items": items,
    }

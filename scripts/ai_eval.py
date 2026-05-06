import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.ai.advisors import generate_advisor_recommendations  # noqa: E402
from app.ai.anomalies import detect_anomalies  # noqa: E402
from app.ai.telemetry import RateLimitEvent  # noqa: E402
from app.observability.telemetry_store import SQLiteTelemetryStore  # noqa: E402


@dataclass(frozen=True)
class EvaluationScenario:
    name: str
    description: str
    events: list[RateLimitEvent]
    expected_recommendations: set[str]
    expected_anomalies: set[str]
    abuse_identifiers: set[str]


def event(
    *,
    timestamp: float,
    route_path: str = "/api/data",
    identifier: str = "free_user",
    allowed: bool = True,
    retry_after_s: int | None = None,
    redis_fail_open: bool = False,
    algorithm: str = "token_bucket",
    fail_mode: str = "open",
    sensitivity: str = "internal",
    capacity: int = 5,
    rate: float = 1.0,
) -> RateLimitEvent:
    return RateLimitEvent(
        timestamp=timestamp,
        route_path=route_path,
        identifier=identifier,
        allowed=allowed,
        remaining=1 if allowed else 0,
        capacity=capacity,
        rate=rate,
        retry_after_s=retry_after_s,
        redis_fail_open=redis_fail_open,
        algorithm=algorithm,
        fail_mode=fail_mode,
        tier="demo",
        owner="ai-eval",
        sensitivity=sensitivity,
        rule_version=1,
        method="GET",
        status_code=200 if allowed else 429,
    )


def normal_free_events(start: float) -> list[RateLimitEvent]:
    return [
        event(timestamp=start + index, identifier=f"free_user_{index % 3}")
        for index in range(10)
    ]


def premium_burst_events(start: float) -> list[RateLimitEvent]:
    return [
        event(
            timestamp=start + index * 0.05,
            identifier="premium_user",
            capacity=100,
            rate=10,
        )
        for index in range(30)
    ]


def abusive_identifier_events(start: float) -> list[RateLimitEvent]:
    return [
        event(
            timestamp=start + index * 0.2,
            identifier="abusive_user",
            allowed=index < 3,
            retry_after_s=None if index < 3 else 1,
        )
        for index in range(10)
    ]


def retry_loop_events(start: float) -> list[RateLimitEvent]:
    return [
        event(
            timestamp=start + index * 0.15,
            route_path="/api/limited-health",
            identifier="retry_loop_user",
            allowed=False,
            retry_after_s=1,
            algorithm="fixed_window",
        )
        for index in range(6)
    ]


def route_spike_events(start: float) -> list[RateLimitEvent]:
    return [
        event(timestamp=start + index * 0.05, identifier=f"spike_user_{index % 10}")
        for index in range(55)
    ]


def sensitive_probe_events(start: float) -> list[RateLimitEvent]:
    return [
        event(
            timestamp=start + index,
            route_path="/api/accounts/{account_id}/data",
            identifier=f"probe_user_{index}",
            sensitivity="sensitive",
            capacity=3,
            rate=0.5,
        )
        for index in range(4)
    ]


def redis_outage_events(start: float) -> list[RateLimitEvent]:
    return [
        event(
            timestamp=start + index,
            route_path="/api/accounts/{account_id}/data",
            identifier="enterprise_user",
            redis_fail_open=True,
            sensitivity="sensitive",
            fail_mode="open",
            capacity=3,
            rate=0.5,
        )
        for index in range(2)
    ]


def fixed_window_pressure_events(start: float) -> list[RateLimitEvent]:
    events = []
    for index in range(25):
        events.append(
            event(
                timestamp=start + index * 0.1,
                route_path="/api/limited-health",
                identifier=f"health_user_{index % 5}",
                allowed=index < 15,
                retry_after_s=None if index < 15 else 1,
                algorithm="fixed_window",
            )
        )
    return events


def mixed_workload_events(start: float) -> list[RateLimitEvent]:
    return [
        *normal_free_events(start),
        *abusive_identifier_events(start + 20),
        *sensitive_probe_events(start + 40),
    ]


def build_scenarios() -> list[EvaluationScenario]:
    return [
        EvaluationScenario(
            name="normal-free-traffic",
            description="Low-volume free-tier traffic should not produce advice or anomalies.",
            events=normal_free_events(1_000),
            expected_recommendations=set(),
            expected_anomalies=set(),
            abuse_identifiers=set(),
        ),
        EvaluationScenario(
            name="premium-burst",
            description="Legitimate premium bursts should avoid abuse/anomaly labels.",
            events=premium_burst_events(2_000),
            expected_recommendations=set(),
            expected_anomalies=set(),
            abuse_identifiers=set(),
        ),
        EvaluationScenario(
            name="abusive-identifier",
            description="One noisy identifier repeatedly hits 429 on a single route.",
            events=abusive_identifier_events(3_000),
            expected_recommendations={"abuse"},
            expected_anomalies={"concentrated_offender", "retry_loop"},
            abuse_identifiers={"abusive_user"},
        ),
        EvaluationScenario(
            name="retry-loop",
            description="A client ignores Retry-After and retries immediately after denials.",
            events=retry_loop_events(4_000),
            expected_recommendations={"abuse"},
            expected_anomalies={"concentrated_offender", "retry_loop"},
            abuse_identifiers={"retry_loop_user"},
        ),
        EvaluationScenario(
            name="route-spike",
            description="High route-wide volume across many identifiers.",
            events=route_spike_events(5_000),
            expected_recommendations=set(),
            expected_anomalies={"route_traffic_spike"},
            abuse_identifiers=set(),
        ),
        EvaluationScenario(
            name="sensitive-route-probing",
            description="Sensitive endpoint traffic spreads across several identifiers.",
            events=sensitive_probe_events(6_000),
            expected_recommendations=set(),
            expected_anomalies={"sensitive_route_probing"},
            abuse_identifiers=set(),
        ),
        EvaluationScenario(
            name="redis-outage-exposure",
            description="Sensitive route is allowed through during Redis fail-open exposure.",
            events=redis_outage_events(7_000),
            expected_recommendations={"reliability"},
            expected_anomalies={"redis_outage_exposure"},
            abuse_identifiers=set(),
        ),
        EvaluationScenario(
            name="fixed-window-pressure",
            description="Broad fixed-window denial pressure should suggest sliding-window review.",
            events=fixed_window_pressure_events(8_000),
            expected_recommendations={"algorithm", "tuning"},
            expected_anomalies=set(),
            abuse_identifiers=set(),
        ),
        EvaluationScenario(
            name="mixed-workload",
            description="Mixed normal, abusive, and sensitive probing traffic.",
            events=mixed_workload_events(9_000),
            expected_recommendations={"abuse"},
            expected_anomalies={
                "concentrated_offender",
                "retry_loop",
                "sensitive_route_probing",
            },
            abuse_identifiers={"abusive_user"},
        ),
    ]


def compare_labels(observed: set[str], expected: set[str]) -> dict[str, Any]:
    true_positive = sorted(observed & expected)
    false_positive = sorted(observed - expected)
    missed = sorted(expected - observed)
    precision = 1.0 if not observed else round(len(true_positive) / len(observed), 4)
    recall = 1.0 if not expected else round(len(true_positive) / len(expected), 4)
    return {
        "expected": sorted(expected),
        "observed": sorted(observed),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "missed": missed,
        "precision": precision,
        "recall": recall,
    }


def persisted_row_to_event(row: dict[str, Any]) -> RateLimitEvent:
    return RateLimitEvent(
        timestamp=float(row["timestamp"]),
        route_path=str(row["route_path"]),
        identifier=str(row["identifier"]),
        allowed=bool(row["allowed"]),
        remaining=int(row["remaining"]),
        capacity=int(row["capacity"]),
        rate=float(row["rate"]),
        retry_after_s=(
            int(row["retry_after_s"]) if row.get("retry_after_s") is not None else None
        ),
        redis_fail_open=bool(row["redis_fail_open"]),
        algorithm=str(row.get("algorithm") or "unknown"),
        fail_mode=str(row.get("fail_mode") or "unknown"),
        tier=row.get("tier"),
        owner=row.get("owner"),
        sensitivity=row.get("sensitivity"),
        rule_version=(
            int(row["rule_version"]) if row.get("rule_version") is not None else None
        ),
        method=row.get("method"),
        status_code=int(row["status_code"]) if row.get("status_code") is not None else None,
        latency_ms=float(row["latency_ms"]) if row.get("latency_ms") is not None else None,
    )


def load_persisted_events(
    db_path: str,
    *,
    since: float | None = None,
    until: float | None = None,
    limit: int = 500,
) -> list[RateLimitEvent]:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Telemetry database does not exist: {db_path}")

    store = SQLiteTelemetryStore(str(path))
    rows = store.recent(limit=limit, since=since, until=until)
    return [persisted_row_to_event(row) for row in reversed(rows)]


def denied_legitimate_estimate(
    events: list[RateLimitEvent],
    abuse_identifiers: set[str],
) -> int:
    return sum(
        1 for item in events if not item.allowed and item.identifier not in abuse_identifiers
    )


def abuse_reduction_estimate(recommendations: dict[str, Any]) -> int:
    return sum(
        int((item.get("signals") or {}).get("rate_limited") or 0)
        for item in recommendations.get("items", [])
        if item.get("type") == "abuse"
    )


def evaluate_scenario(
    scenario: EvaluationScenario,
    *,
    generated_at: int,
) -> dict[str, Any]:
    recommendations = generate_advisor_recommendations(
        scenario.events,
        generated_at=generated_at,
    )
    anomalies = detect_anomalies(scenario.events, generated_at=generated_at)
    observed_recommendations = {item["type"] for item in recommendations["items"]}
    observed_anomalies = {item["type"] for item in anomalies["findings"]}
    recommendation_quality = compare_labels(
        observed_recommendations,
        scenario.expected_recommendations,
    )
    anomaly_quality = compare_labels(observed_anomalies, scenario.expected_anomalies)
    stable = not (
        recommendation_quality["false_positive"]
        or recommendation_quality["missed"]
        or anomaly_quality["false_positive"]
        or anomaly_quality["missed"]
    )

    return {
        "name": scenario.name,
        "description": scenario.description,
        "events": len(scenario.events),
        "denied": sum(1 for item in scenario.events if not item.allowed),
        "recommendations": recommendation_quality,
        "anomalies": anomaly_quality,
        "denied_legitimate_estimate": denied_legitimate_estimate(
            scenario.events,
            scenario.abuse_identifiers,
        ),
        "abuse_reduction_estimate": abuse_reduction_estimate(recommendations),
        "policy_stability": "stable" if stable else "review",
    }


def evaluate_event_window(
    *,
    name: str,
    description: str,
    events: list[RateLimitEvent],
    generated_at: int,
    expected_recommendations: set[str] | None = None,
    expected_anomalies: set[str] | None = None,
    abuse_identifiers: set[str] | None = None,
) -> dict[str, Any]:
    expected_recommendations = expected_recommendations or set()
    expected_anomalies = expected_anomalies or set()
    abuse_identifiers = abuse_identifiers or set()
    recommendations = generate_advisor_recommendations(events, generated_at=generated_at)
    anomalies = detect_anomalies(events, generated_at=generated_at)
    observed_recommendations = {item["type"] for item in recommendations["items"]}
    observed_anomalies = {item["type"] for item in anomalies["findings"]}
    recommendation_quality = compare_labels(
        observed_recommendations,
        expected_recommendations,
    )
    anomaly_quality = compare_labels(observed_anomalies, expected_anomalies)
    has_expectations = bool(expected_recommendations or expected_anomalies)
    stable = bool(events) and not (
        recommendation_quality["false_positive"]
        or recommendation_quality["missed"]
        or anomaly_quality["false_positive"]
        or anomaly_quality["missed"]
    )

    return {
        "name": name,
        "description": description,
        "events": len(events),
        "denied": sum(1 for item in events if not item.allowed),
        "time_range": {
            "first": min((item.timestamp for item in events), default=None),
            "last": max((item.timestamp for item in events), default=None),
        },
        "recommendations": recommendation_quality,
        "anomalies": anomaly_quality,
        "observed": {
            "recommendations": sorted(observed_recommendations),
            "anomalies": sorted(observed_anomalies),
        },
        "has_expectations": has_expectations,
        "denied_legitimate_estimate": denied_legitimate_estimate(
            events,
            abuse_identifiers,
        ),
        "abuse_reduction_estimate": abuse_reduction_estimate(recommendations),
        "policy_stability": "stable" if stable else "review",
    }


def _combined_precision(scenarios: list[dict[str, Any]], key: str) -> float:
    observed = sum(len(item[key]["observed"]) for item in scenarios)
    true_positive = sum(len(item[key]["true_positive"]) for item in scenarios)
    if observed == 0:
        return 1.0
    return round(true_positive / observed, 4)


def _combined_recall(scenarios: list[dict[str, Any]], key: str) -> float:
    expected = sum(len(item[key]["expected"]) for item in scenarios)
    true_positive = sum(len(item[key]["true_positive"]) for item in scenarios)
    if expected == 0:
        return 1.0
    return round(true_positive / expected, 4)


def false_positive_notes(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notes = []
    for item in scenarios:
        recommendation_false_positive = item["recommendations"]["false_positive"]
        anomaly_false_positive = item["anomalies"]["false_positive"]
        if recommendation_false_positive or anomaly_false_positive:
            notes.append({
                "scenario": item["name"],
                "recommendations": recommendation_false_positive,
                "anomalies": anomaly_false_positive,
            })
    return notes


def summarize_evaluation(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    stable_scenarios = sum(1 for item in scenarios if item["policy_stability"] == "stable")
    return {
        "scenarios": len(scenarios),
        "stable_scenarios": stable_scenarios,
        "policy_stability": "stable" if stable_scenarios == len(scenarios) else "review",
        "recommendation_precision": _combined_precision(scenarios, "recommendations"),
        "recommendation_recall": _combined_recall(scenarios, "recommendations"),
        "anomaly_precision": _combined_precision(scenarios, "anomalies"),
        "anomaly_recall": _combined_recall(scenarios, "anomalies"),
        "false_positive_notes": false_positive_notes(scenarios),
        "denied_legitimate_estimate": sum(
            item["denied_legitimate_estimate"] for item in scenarios
        ),
        "abuse_reduction_estimate": sum(
            item["abuse_reduction_estimate"] for item in scenarios
        ),
    }


def run_evaluation(*, generated_at: int = 1_734_000_000) -> dict[str, Any]:
    scenario_results = [
        evaluate_scenario(scenario, generated_at=generated_at)
        for scenario in build_scenarios()
    ]
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "summary": summarize_evaluation(scenario_results),
        "scenarios": scenario_results,
        "limitations": [
            "Synthetic events exercise advisor logic, not end-to-end Redis timing.",
            "Precision and recall are label-level checks against hand-authored expectations.",
            "Abuse-reduction estimates are based on denied abusive requests, not live mitigation.",
        ],
    }


def run_persistent_evaluation(
    *,
    db_path: str,
    since: float | None = None,
    until: float | None = None,
    limit: int = 500,
    window_name: str = "persisted-telemetry-window",
    expected_scenario: str | None = None,
    generated_at: int = 1_734_000_000,
) -> dict[str, Any]:
    scenario_by_name = {scenario.name: scenario for scenario in build_scenarios()}
    expected = scenario_by_name.get(expected_scenario or "")
    if expected_scenario and expected is None:
        raise ValueError(f"Unknown expected scenario: {expected_scenario}")

    events = load_persisted_events(db_path, since=since, until=until, limit=limit)
    scenario_result = evaluate_event_window(
        name=window_name,
        description="Persisted telemetry replay window from SQLite.",
        events=events,
        generated_at=generated_at,
        expected_recommendations=expected.expected_recommendations if expected else None,
        expected_anomalies=expected.expected_anomalies if expected else None,
        abuse_identifiers=expected.abuse_identifiers if expected else None,
    )
    return {
        "schema_version": 1,
        "mode": "persistent_window",
        "generated_at": generated_at,
        "source": {
            "telemetry_db": db_path,
            "since": since,
            "until": until,
            "limit": limit,
            "expected_scenario": expected_scenario,
        },
        "summary": summarize_evaluation([scenario_result])
        if scenario_result["has_expectations"]
        else {
            "events": scenario_result["events"],
            "denied": scenario_result["denied"],
            "observed_recommendations": scenario_result["observed"]["recommendations"],
            "observed_anomalies": scenario_result["observed"]["anomalies"],
            "policy_stability": scenario_result["policy_stability"],
        },
        "scenarios": [scenario_result],
        "limitations": [
            "Persisted evaluation replays stored telemetry and does not generate traffic.",
            "Precision and recall are only meaningful when --expected-scenario is supplied.",
            "Evaluation quality depends on the selected time window and event limit.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic AI advisor evaluation.")
    parser.add_argument("--output", help="Optional path to write the JSON report.")
    parser.add_argument(
        "--telemetry-db",
        help="Optional SQLite telemetry database path to evaluate instead of synthetic scenarios.",
    )
    parser.add_argument("--since", type=float, help="Inclusive Unix timestamp lower bound.")
    parser.add_argument("--until", type=float, help="Inclusive Unix timestamp upper bound.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum persisted events.")
    parser.add_argument(
        "--window-name",
        default="persisted-telemetry-window",
        help="Name to use for a persisted telemetry evaluation window.",
    )
    parser.add_argument(
        "--expected-scenario",
        help="Optional synthetic scenario name for label comparison.",
    )
    args = parser.parse_args()

    if args.telemetry_db:
        report = run_persistent_evaluation(
            db_path=args.telemetry_db,
            since=args.since,
            until=args.until,
            limit=args.limit,
            window_name=args.window_name,
            expected_scenario=args.expected_scenario,
        )
    else:
        report = run_evaluation()

    rendered = json.dumps(report, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{rendered}\n", encoding="utf-8")

    print(rendered)


if __name__ == "__main__":
    main()

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.ai.advisors import generate_advisor_recommendations  # noqa: E402
from app.ai.anomalies import detect_anomalies  # noqa: E402
from app.ai.telemetry import RateLimitEvent  # noqa: E402
from scripts.ai_eval import (  # noqa: E402
    EvaluationScenario,
    build_scenarios,
    compare_labels,
    run_evaluation,
)
from scripts.redis_outage_demo import compose_args, run_command  # noqa: E402


@dataclass(frozen=True)
class LiveScenario:
    name: str
    description: str
    requests: list[tuple[str, str]]
    concurrency: int = 4


@dataclass(frozen=True)
class CapturedResponse:
    scenario: str
    endpoint: str
    api_key: str
    timestamp: float
    status: int | str
    latency_ms: float
    headers: dict[str, str]
    error: str | None = None
    redis_fail_open: bool = False


def _prefixed_key(prefix: str, value: str) -> str:
    return f"{prefix}_{value}"


def build_live_scenarios(*, run_id: str | None = None) -> list[LiveScenario]:
    prefix = run_id or f"live_{int(time.time())}"
    return [
        LiveScenario(
            name="normal-free-traffic",
            description="Low-volume free-tier traffic through the live HTTP API.",
            requests=[
                ("/api/data", _prefixed_key(prefix, f"normal_free_{index % 3}"))
                for index in range(10)
            ],
            concurrency=3,
        ),
        LiveScenario(
            name="premium-burst",
            description="Premium override traffic through the live HTTP API.",
            requests=[("/api/data", "premium_user_key") for _ in range(30)],
            concurrency=6,
        ),
        LiveScenario(
            name="abusive-identifier",
            description="One live identifier repeatedly exhausts the token bucket.",
            requests=[
                ("/api/data", _prefixed_key(prefix, "abusive_identifier"))
                for _ in range(10)
            ],
            concurrency=1,
        ),
        LiveScenario(
            name="retry-loop",
            description="One live fixed-window client retries after denials.",
            requests=[
                ("/api/limited-health", _prefixed_key(prefix, "retry_loop"))
                for _ in range(16)
            ],
            concurrency=1,
        ),
        LiveScenario(
            name="route-spike",
            description="High live route volume spread across many identifiers.",
            requests=[
                ("/api/data", _prefixed_key(prefix, f"spike_{index}"))
                for index in range(55)
            ],
            concurrency=10,
        ),
        LiveScenario(
            name="sensitive-route-probing",
            description="Sensitive live route traffic spread across identifiers.",
            requests=[
                (
                    f"/api/accounts/live-eval-{index}/data",
                    _prefixed_key(prefix, f"probe_{index}"),
                )
                for index in range(4)
            ],
            concurrency=4,
        ),
        LiveScenario(
            name="fixed-window-pressure",
            description="Broad fixed-window live pressure across several identifiers.",
            requests=[
                ("/api/limited-health", _prefixed_key(prefix, f"fixed_window_{index % 4}"))
                for index in range(48)
            ],
            concurrency=8,
        ),
    ]


def build_redis_outage_scenario(*, run_id: str | None = None) -> LiveScenario:
    prefix = run_id or f"live_{int(time.time())}"
    return LiveScenario(
        name="redis-outage-exposure",
        description="Sensitive live route is allowed during a managed Redis outage.",
        requests=[
            (
                f"/api/accounts/live-outage-{index}/data",
                _prefixed_key(prefix, "redis_outage_enterprise"),
            )
            for index in range(2)
        ],
        concurrency=1,
    )


def route_template(endpoint: str) -> str:
    if endpoint.startswith("/api/accounts/") and endpoint.endswith("/data"):
        return "/api/accounts/{account_id}/data"
    return endpoint


def route_metadata(route_path: str, api_key: str, headers: dict[str, str]) -> dict[str, Any]:
    algorithm = headers.get("X-RateLimit-Algorithm") or "unknown"
    capacity = int(headers.get("X-RateLimit-Limit") or 0)
    if route_path == "/api/limited-health":
        return {
            "capacity": capacity or 10,
            "rate": 5.0,
            "algorithm": algorithm,
            "fail_mode": "closed",
            "tier": "platform",
            "owner": "sre",
            "sensitivity": "public",
        }
    if route_path == "/api/accounts/{account_id}/data":
        return {
            "capacity": capacity or 5,
            "rate": 1.0,
            "algorithm": algorithm,
            "fail_mode": "open",
            "tier": "free",
            "owner": "accounts",
            "sensitivity": "sensitive",
        }
    if api_key == "premium_user_key":
        return {
            "capacity": capacity or 100,
            "rate": 10.0,
            "algorithm": algorithm,
            "fail_mode": "open",
            "tier": "premium",
            "owner": "customer-platform",
            "sensitivity": "internal",
        }
    return {
        "capacity": capacity or 5,
        "rate": 1.0,
        "algorithm": algorithm,
        "fail_mode": "open",
        "tier": "free",
        "owner": "api-platform",
        "sensitivity": "internal",
    }


def send_request(
    base_url: str,
    *,
    scenario: str,
    endpoint: str,
    api_key: str,
    timeout_s: float,
    redis_fail_open: bool = False,
) -> CapturedResponse:
    request = Request(
        f"{base_url.rstrip('/')}{endpoint}",
        headers={"X-API-Key": api_key},
        method="GET",
    )
    started = time.perf_counter()
    timestamp = time.time()

    try:
        with urlopen(request, timeout=timeout_s) as response:
            response.read()
            status: int | str = response.status
            headers = dict(response.headers.items())
            error = None
    except HTTPError as exc:
        exc.read()
        status = exc.code
        headers = dict(exc.headers.items())
        error = None
    except URLError as exc:
        status = "error"
        headers = {}
        error = str(exc.reason)

    return CapturedResponse(
        scenario=scenario,
        endpoint=endpoint,
        api_key=api_key,
        timestamp=timestamp,
        status=status,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        headers=headers,
        error=error,
        redis_fail_open=redis_fail_open,
    )


def run_live_scenario(
    base_url: str,
    scenario: LiveScenario,
    *,
    timeout_s: float,
    redis_fail_open: bool = False,
) -> list[CapturedResponse]:
    captures: list[CapturedResponse] = []
    with ThreadPoolExecutor(max_workers=scenario.concurrency) as pool:
        futures = [
            pool.submit(
                send_request,
                base_url,
                scenario=scenario.name,
                endpoint=endpoint,
                api_key=api_key,
                timeout_s=timeout_s,
                redis_fail_open=redis_fail_open,
            )
            for endpoint, api_key in scenario.requests
        ]
        for future in as_completed(futures):
            captures.append(future.result())

    return sorted(captures, key=lambda item: item.timestamp)


def run_redis_outage_scenario(
    base_url: str,
    scenario: LiveScenario,
    *,
    compose_command: str,
    redis_service: str,
    settle_seconds: float,
    restore_seconds: float,
    skip_stop: bool,
    skip_restore: bool,
    timeout_s: float,
) -> dict[str, Any]:
    commands = []
    stopped_redis = False
    if not skip_stop:
        stop_result = run_command(compose_args(compose_command, "stop", redis_service))
        commands.append(stop_result)
        stopped_redis = stop_result["returncode"] == 0
        time.sleep(settle_seconds)

    captures = run_live_scenario(
        base_url,
        scenario,
        timeout_s=timeout_s,
        redis_fail_open=True,
    )

    if stopped_redis and not skip_restore:
        start_result = run_command(compose_args(compose_command, "start", redis_service))
        commands.append(start_result)
        time.sleep(restore_seconds)

    return {
        "managed_outage": not skip_stop,
        "redis_service": redis_service,
        "commands": commands,
        "captures": captures,
        "restored": stopped_redis and not skip_restore,
    }


def captured_response_to_event(capture: CapturedResponse) -> RateLimitEvent | None:
    if capture.status == "error":
        return None

    route_path = route_template(capture.endpoint)
    metadata = route_metadata(route_path, capture.api_key, capture.headers)
    status_code = int(capture.status)
    retry_after = capture.headers.get("Retry-After")
    remaining = capture.headers.get("X-RateLimit-Remaining")
    return RateLimitEvent(
        timestamp=capture.timestamp,
        route_path=route_path,
        identifier=capture.api_key,
        allowed=status_code < 400,
        remaining=int(remaining) if remaining is not None else 0,
        capacity=metadata["capacity"],
        rate=metadata["rate"],
        retry_after_s=int(retry_after) if retry_after is not None else None,
        redis_fail_open=capture.redis_fail_open,
        algorithm=metadata["algorithm"],
        fail_mode=metadata["fail_mode"],
        tier=metadata["tier"],
        owner=metadata["owner"],
        sensitivity=metadata["sensitivity"],
        rule_version=1,
        method="GET",
        status_code=status_code,
        latency_ms=capture.latency_ms,
    )


def capture_summary(captures: list[CapturedResponse]) -> dict[str, Any]:
    statuses = Counter(str(item.status) for item in captures)
    return {
        "requests": len(captures),
        "limited": statuses.get("429", 0),
        "errors": statuses.get("error", 0)
        + sum(count for status, count in statuses.items() if status.startswith("5")),
        "redis_fail_open": sum(1 for item in captures if item.redis_fail_open),
        "statuses": dict(sorted(statuses.items())),
    }


def _synthetic_by_name(generated_at: int) -> dict[str, dict[str, Any]]:
    return {
        item["name"]: item
        for item in run_evaluation(generated_at=generated_at)["scenarios"]
    }


def _scenario_definition_by_name() -> dict[str, EvaluationScenario]:
    return {scenario.name: scenario for scenario in build_scenarios()}


def evaluate_live_captures(
    scenario: LiveScenario,
    captures: list[CapturedResponse],
    *,
    generated_at: int,
    synthetic_result: dict[str, Any] | None,
    scenario_definition: EvaluationScenario | None,
) -> dict[str, Any]:
    summary = capture_summary(captures)
    events = [
        event
        for capture in captures
        if (event := captured_response_to_event(capture)) is not None
    ]
    recommendations = generate_advisor_recommendations(events, generated_at=generated_at)
    anomalies = detect_anomalies(events, generated_at=generated_at)
    observed_recommendations = {item["type"] for item in recommendations["items"]}
    observed_anomalies = {item["type"] for item in anomalies["findings"]}
    expected_recommendations = (
        scenario_definition.expected_recommendations if scenario_definition else set()
    )
    expected_anomalies = scenario_definition.expected_anomalies if scenario_definition else set()

    recommendation_quality = compare_labels(
        observed_recommendations,
        expected_recommendations,
    )
    anomaly_quality = compare_labels(observed_anomalies, expected_anomalies)
    synthetic_recommendations = set(
        (synthetic_result or {}).get("recommendations", {}).get("observed", [])
    )
    synthetic_anomalies = set(
        (synthetic_result or {}).get("anomalies", {}).get("observed", [])
    )
    matches_synthetic = (
        summary["errors"] == 0
        and len(events) == len(captures)
        and bool(captures)
        and observed_recommendations == synthetic_recommendations
        and observed_anomalies == synthetic_anomalies
    )
    stable = not (
        summary["errors"]
        or len(events) != len(captures)
        or not captures
        or recommendation_quality["false_positive"]
        or recommendation_quality["missed"]
        or anomaly_quality["false_positive"]
        or anomaly_quality["missed"]
    )

    return {
        "name": scenario.name,
        "description": scenario.description,
        "capture": summary,
        "events_evaluated": len(events),
        "recommendations": recommendation_quality,
        "anomalies": anomaly_quality,
        "synthetic_observed": {
            "recommendations": sorted(synthetic_recommendations),
            "anomalies": sorted(synthetic_anomalies),
        },
        "matches_synthetic_observed": matches_synthetic,
        "policy_stability": "stable" if stable else "review",
    }


def summarize_live_evaluation(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    stable = sum(1 for item in scenarios if item["policy_stability"] == "stable")
    matches = sum(1 for item in scenarios if item["matches_synthetic_observed"])
    return {
        "live_scenarios": len(scenarios),
        "stable_live_scenarios": stable,
        "synthetic_matches": matches,
        "live_policy_stability": "stable" if stable == len(scenarios) else "review",
        "synthetic_agreement": "matched" if matches == len(scenarios) else "review",
    }


def check_readiness(base_url: str, *, timeout_s: float) -> dict[str, Any]:
    request = Request(f"{base_url.rstrip('/')}/ready", method="GET")
    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {"ready": response.status == 200, "status": response.status, "body": body}
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ready": False, "status": "error", "error": str(exc)}


def run_live_evaluation(
    *,
    base_url: str,
    generated_at: int | None = None,
    run_id: str | None = None,
    scenario_names: set[str] | None = None,
    timeout_s: float = 5.0,
    skip_readiness: bool = False,
    include_redis_outage: bool = False,
    compose_command: str = "docker compose",
    redis_service: str = "redis",
    settle_seconds: float = 2.0,
    restore_seconds: float = 4.0,
    skip_redis_stop: bool = False,
    skip_redis_restore: bool = False,
) -> dict[str, Any]:
    generated_at = generated_at or int(time.time())
    readiness = (
        {"ready": None, "skipped": True}
        if skip_readiness
        else check_readiness(base_url, timeout_s=timeout_s)
    )
    synthetic_results = _synthetic_by_name(generated_at)
    scenario_definitions = _scenario_definition_by_name()
    live_scenarios = [
        scenario
        for scenario in build_live_scenarios(run_id=run_id)
        if scenario_names is None or scenario.name in scenario_names
    ]
    outage_scenario = build_redis_outage_scenario(run_id=run_id)
    if include_redis_outage and (
        scenario_names is None or outage_scenario.name in scenario_names
    ):
        live_scenarios.append(outage_scenario)

    scenario_results = []
    outage_runs = []
    for scenario in live_scenarios:
        if scenario.name == "redis-outage-exposure":
            outage_run = run_redis_outage_scenario(
                base_url,
                scenario,
                compose_command=compose_command,
                redis_service=redis_service,
                settle_seconds=settle_seconds,
                restore_seconds=restore_seconds,
                skip_stop=skip_redis_stop,
                skip_restore=skip_redis_restore,
                timeout_s=timeout_s,
            )
            captures = outage_run["captures"]
            outage_runs.append({k: v for k, v in outage_run.items() if k != "captures"})
        else:
            captures = run_live_scenario(base_url, scenario, timeout_s=timeout_s)

        scenario_result = evaluate_live_captures(
            scenario,
            captures,
            generated_at=generated_at,
            synthetic_result=synthetic_results.get(scenario.name),
            scenario_definition=scenario_definitions.get(scenario.name),
        )
        if scenario.name == "redis-outage-exposure" and outage_runs:
            scenario_result["outage"] = outage_runs[-1]
        scenario_results.append(scenario_result)

    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "base_url": base_url,
        "readiness": readiness,
        "summary": summarize_live_evaluation(scenario_results),
        "scenarios": scenario_results,
        "outage_runs": outage_runs,
        "limitations": [
            (
                "Live captures use HTTP response headers and status codes to rebuild "
                "evaluation events."
            ),
            (
                "Redis outage exposure only runs when --include-redis-outage is set "
                "because it intentionally stops or assumes unavailable Redis."
            ),
            "Repeated runs should use a fresh run_id or wait for rate-limit windows to decay.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run live HTTP AI advisor evaluation against a running app."
    )
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--output", help="Optional path to write the JSON report.")
    parser.add_argument("--run-id", help="Optional unique prefix for generated API keys.")
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help="Scenario name to run. Can be provided more than once.",
    )
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--skip-readiness", action="store_true")
    parser.add_argument(
        "--include-redis-outage",
        action="store_true",
        help="Include the managed Redis outage reliability scenario.",
    )
    parser.add_argument("--compose-command", default="docker compose")
    parser.add_argument("--redis-service", default="redis")
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--restore-seconds", type=float, default=4.0)
    parser.add_argument(
        "--skip-redis-stop",
        action="store_true",
        help="Assume Redis is already unavailable and only run outage captures.",
    )
    parser.add_argument(
        "--skip-redis-restore",
        action="store_true",
        help="Leave Redis stopped after a managed outage capture.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when live labels diverge from the synthetic baseline.",
    )
    args = parser.parse_args()

    report = run_live_evaluation(
        base_url=args.base_url,
        run_id=args.run_id,
        scenario_names=set(args.scenarios) if args.scenarios else None,
        timeout_s=args.timeout_s,
        skip_readiness=args.skip_readiness,
        include_redis_outage=args.include_redis_outage,
        compose_command=args.compose_command,
        redis_service=args.redis_service,
        settle_seconds=args.settle_seconds,
        restore_seconds=args.restore_seconds,
        skip_redis_stop=args.skip_redis_stop,
        skip_redis_restore=args.skip_redis_restore,
    )
    rendered = json.dumps(report, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{rendered}\n", encoding="utf-8")

    print(rendered)
    if report["readiness"].get("ready") is False:
        raise SystemExit(2)
    if args.strict and report["summary"].get("synthetic_agreement") != "matched":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

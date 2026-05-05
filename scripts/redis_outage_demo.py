import argparse
import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Probe:
    name: str
    endpoint: str
    api_key: str
    expected_status: int | None
    expectation: str


PROBES = [
    Probe(
        name="fail-open",
        endpoint="/api/data",
        api_key="outage_fail_open_demo",
        expected_status=200,
        expectation="Redis outage should allow this request because /api/data uses fail_mode=open.",
    ),
    Probe(
        name="fail-closed",
        endpoint="/api/limited-health",
        api_key="outage_fail_closed_demo",
        expected_status=429,
        expectation=(
            "Redis outage should reject this request because /api/limited-health "
            "uses fail_mode=closed."
        ),
    ),
]


def compose_args(compose_command: str, action: str, service: str) -> list[str]:
    base = shlex.split(compose_command)
    if action == "stop":
        return [*base, "stop", service]
    if action == "start":
        return [*base, "up", "-d", service]
    raise ValueError(f"Unknown compose action: {action}")


def run_command(args: list[str]) -> dict:
    started = time.perf_counter()
    completed = subprocess.run(  # noqa: S603
        args,
        capture_output=True,
        check=False,
        text=True,
    )
    return {
        "command": " ".join(args),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def read_response(url: str, api_key: str | None = None, timeout: float = 5.0) -> dict:
    headers = {"X-API-Key": api_key} if api_key else {}
    request = Request(url, headers=headers, method="GET")
    started = time.perf_counter()

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response_result(response.status, response.headers, body, started)
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return response_result(exc.code, exc.headers, body, started)
    except URLError as exc:
        return {
            "status": "error",
            "error": str(exc.reason),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def response_result(status: int, headers, body: str, started: float) -> dict:
    return {
        "status": status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "remaining": headers.get("X-RateLimit-Remaining"),
        "retry_after": headers.get("Retry-After"),
        "request_id": headers.get("X-Request-ID"),
        "body": body,
    }


def probe_route(base_url: str, probe: Probe, phase: str) -> dict:
    url = f"{base_url.rstrip('/')}{probe.endpoint}"
    result = read_response(url, api_key=probe.api_key)
    observed_status = result.get("status")
    return {
        "phase": phase,
        "name": probe.name,
        "endpoint": probe.endpoint,
        "expected_status": probe.expected_status,
        "observed_status": observed_status,
        "matched": observed_status == probe.expected_status,
        "expectation": probe.expectation,
        **result,
    }


def ready_probe(base_url: str, phase: str) -> dict:
    result = read_response(f"{base_url.rstrip('/')}/ready")
    return {"phase": phase, "name": "readiness", **result}


def run_demo(args) -> dict:
    commands = []
    probes = [ready_probe(args.base_url, "before-outage")]

    for probe in PROBES:
        probes.append(probe_route(args.base_url, probe, "before-outage"))

    stopped_redis = False
    if not args.skip_stop:
        stop_result = run_command(compose_args(args.compose_command, "stop", args.redis_service))
        commands.append(stop_result)
        stopped_redis = stop_result["returncode"] == 0
        time.sleep(args.settle_seconds)

    probes.append(ready_probe(args.base_url, "during-outage"))
    for probe in PROBES:
        probes.append(probe_route(args.base_url, probe, "during-outage"))

    if stopped_redis and not args.skip_restore:
        start_args = compose_args(args.compose_command, "start", args.redis_service)
        commands.append(run_command(start_args))
        time.sleep(args.restore_seconds)
        probes.append(ready_probe(args.base_url, "after-restore"))

    return {
        "base_url": args.base_url,
        "redis_service": args.redis_service,
        "managed_outage": not args.skip_stop,
        "commands": commands,
        "probes": probes,
        "summary": summarize(probes),
    }


def summarize(probes: list[dict]) -> dict:
    during = [probe for probe in probes if probe.get("phase") == "during-outage"]
    route_probes = [probe for probe in during if probe.get("expected_status") is not None]
    return {
        "during_outage_checks": len(route_probes),
        "matched_expectations": sum(1 for probe in route_probes if probe.get("matched")),
        "fail_open_status": next(
            (
                probe.get("observed_status")
                for probe in route_probes
                if probe.get("name") == "fail-open"
            ),
            None,
        ),
        "fail_closed_status": next(
            (
                probe.get("observed_status")
                for probe in route_probes
                if probe.get("name") == "fail-closed"
            ),
            None,
        ),
    }


def print_human(result: dict) -> None:
    print("Redis outage demo")
    print(f"Base URL: {result['base_url']}")
    print("")

    if result["commands"]:
        print("Commands")
        for command in result["commands"]:
            print(f"- {command['command']} -> {command['returncode']}")
            if command["stderr"]:
                print(f"  stderr: {command['stderr']}")
        print("")

    print("Probes")
    for probe in result["probes"]:
        expected = probe.get("expected_status")
        expectation = f" expected={expected}" if expected is not None else ""
        matched = probe.get("matched")
        suffix = ""
        if matched is not None:
            suffix = " OK" if matched else " CHECK"
        status = probe.get("observed_status", probe.get("status"))
        print(
            f"- {probe['phase']} {probe['name']}: status={status}"
            f"{expectation}{suffix}"
        )
    print("")
    print(json.dumps(result["summary"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demonstrate fail-open and fail-closed behavior during a Redis outage."
    )
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--compose-command", default="docker compose")
    parser.add_argument("--redis-service", default="redis")
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--restore-seconds", type=float, default=4.0)
    parser.add_argument("--skip-stop", action="store_true", help="Probe without stopping Redis.")
    parser.add_argument(
        "--skip-restore",
        action="store_true",
        help="Leave Redis stopped after the outage probe.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args()

    result = run_demo(args)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_human(result)


if __name__ == "__main__":
    main()

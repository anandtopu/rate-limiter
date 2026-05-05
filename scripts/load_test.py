import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Scenario:
    name: str
    api_key: str
    endpoint: str
    requests: int
    concurrency: int


SCENARIOS = [
    Scenario("free-data", "free_user_key", "/api/data", 12, 4),
    Scenario("premium-data", "premium_user_key", "/api/data", 12, 4),
    Scenario("limited-health", "abusive_user_key", "/api/limited-health", 14, 6),
]


def send_request(base_url: str, scenario: Scenario) -> dict:
    request = Request(
        f"{base_url.rstrip('/')}{scenario.endpoint}",
        headers={"X-API-Key": scenario.api_key},
        method="GET",
    )
    started = time.perf_counter()

    try:
        with urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            status = response.status
            headers = response.headers
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        status = exc.code
        headers = exc.headers
    except URLError as exc:
        return {
            "scenario": scenario.name,
            "status": "error",
            "error": str(exc.reason),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    return {
        "scenario": scenario.name,
        "status": status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "remaining": headers.get("X-RateLimit-Remaining"),
        "retry_after": headers.get("Retry-After"),
        "body": body,
    }


def run_scenario(base_url: str, scenario: Scenario) -> list[dict]:
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=scenario.concurrency) as pool:
        futures = [pool.submit(send_request, base_url, scenario) for _ in range(scenario.requests)]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def summarize(results: list[dict]) -> dict:
    summary: dict[str, dict[str, int | float]] = {}
    for item in results:
        scenario = item["scenario"]
        bucket = summary.setdefault(scenario, {"requests": 0, "limited": 0, "errors": 0})
        bucket["requests"] += 1
        if item["status"] == 429:
            bucket["limited"] += 1
        elif item["status"] == "error" or int(item["status"]) >= 500:
            bucket["errors"] += 1
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small rate limiter demo load test.")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--json", action="store_true", help="Print raw result JSON.")
    args = parser.parse_args()

    results: list[dict] = []
    for scenario in SCENARIOS:
        results.extend(run_scenario(args.base_url, scenario))

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print(json.dumps(summarize(results), indent=2))


if __name__ == "__main__":
    main()

import json
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

from scripts import ai_eval, ai_live_eval


def captures_from_events(scenario_name, events):
    captures = []
    for event in events:
        endpoint = event.route_path
        if endpoint == "/api/accounts/{account_id}/data":
            endpoint = "/api/accounts/test-account/data"
        headers = {
            "X-RateLimit-Limit": str(event.capacity),
            "X-RateLimit-Remaining": str(event.remaining),
            "X-RateLimit-Algorithm": event.algorithm,
        }
        if event.retry_after_s is not None:
            headers["Retry-After"] = str(event.retry_after_s)
        captures.append(
            ai_live_eval.CapturedResponse(
                scenario=scenario_name,
                endpoint=endpoint,
                api_key=event.identifier,
                timestamp=event.timestamp,
                status=event.status_code,
                latency_ms=1.0,
                headers=headers,
            )
        )
    return captures


def test_live_ai_eval_scenarios_cover_synthetic_comparison_cases():
    live_names = {scenario.name for scenario in ai_live_eval.build_live_scenarios(run_id="t")}

    assert {
        "normal-free-traffic",
        "premium-burst",
        "abusive-identifier",
        "retry-loop",
        "route-spike",
        "sensitive-route-probing",
        "fixed-window-pressure",
    }.issubset(live_names)
    assert "redis-outage-exposure" not in live_names


def test_live_ai_eval_rebuilds_events_from_captured_http_responses():
    capture = ai_live_eval.CapturedResponse(
        scenario="fixed-window-pressure",
        endpoint="/api/limited-health",
        api_key="live-user",
        timestamp=123.0,
        status=429,
        latency_ms=2.5,
        headers={
            "X-RateLimit-Limit": "10",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Algorithm": "fixed_window",
            "Retry-After": "1",
        },
    )

    event = ai_live_eval.captured_response_to_event(capture)

    assert event is not None
    assert event.route_path == "/api/limited-health"
    assert event.identifier == "live-user"
    assert event.allowed is False
    assert event.capacity == 10
    assert event.algorithm == "fixed_window"
    assert event.fail_mode == "closed"
    assert event.retry_after_s == 1


def test_live_ai_eval_route_helpers_cover_templates_and_metadata():
    assert (
        ai_live_eval.route_template("/api/accounts/acct-1/data")
        == "/api/accounts/{account_id}/data"
    )
    account = ai_live_eval.route_metadata(
        "/api/accounts/{account_id}/data",
        "user",
        {"X-RateLimit-Algorithm": "sliding_window"},
    )
    premium = ai_live_eval.route_metadata(
        "/api/data",
        "premium_user_key",
        {"X-RateLimit-Limit": "100", "X-RateLimit-Algorithm": "token_bucket"},
    )

    assert account["owner"] == "accounts"
    assert account["sensitivity"] == "sensitive"
    assert premium["tier"] == "premium"
    assert premium["rate"] == 10.0


def test_live_ai_eval_send_request_captures_success_http_errors_and_url_errors(monkeypatch):
    class FakeResponse:
        status = 200
        headers = {"X-RateLimit-Limit": "5"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b"{}"

    monkeypatch.setattr("scripts.ai_live_eval.urlopen", lambda request, timeout: FakeResponse())
    success = ai_live_eval.send_request(
        "http://test",
        scenario="normal-free-traffic",
        endpoint="/api/data",
        api_key="user",
        timeout_s=1,
    )
    assert success.status == 200
    assert success.headers["X-RateLimit-Limit"] == "5"

    def raise_http_error(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "1"},
            fp=BytesIO(b"{}"),
        )

    monkeypatch.setattr("scripts.ai_live_eval.urlopen", raise_http_error)
    limited = ai_live_eval.send_request(
        "http://test",
        scenario="abusive-identifier",
        endpoint="/api/data",
        api_key="user",
        timeout_s=1,
    )
    assert limited.status == 429
    assert limited.headers["Retry-After"] == "1"

    def raise_url_error(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("scripts.ai_live_eval.urlopen", raise_url_error)
    failed = ai_live_eval.send_request(
        "http://test",
        scenario="normal-free-traffic",
        endpoint="/api/data",
        api_key="user",
        timeout_s=1,
    )
    assert failed.status == "error"
    assert failed.error == "connection refused"


def test_live_ai_eval_run_live_scenario_and_readiness(monkeypatch):
    def fake_send_request(base_url, *, scenario, endpoint, api_key, timeout_s):
        return ai_live_eval.CapturedResponse(
            scenario=scenario,
            endpoint=endpoint,
            api_key=api_key,
            timestamp=2.0 if api_key == "second" else 1.0,
            status=200,
            latency_ms=1.0,
            headers={},
        )

    monkeypatch.setattr(ai_live_eval, "send_request", fake_send_request)
    scenario = ai_live_eval.LiveScenario(
        name="normal-free-traffic",
        description="test",
        requests=[("/api/data", "second"), ("/api/data", "first")],
        concurrency=2,
    )

    captures = ai_live_eval.run_live_scenario("http://test", scenario, timeout_s=1)

    assert [capture.api_key for capture in captures] == ["first", "second"]

    class FakeReadyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"status":"ready"}'

    monkeypatch.setattr(
        "scripts.ai_live_eval.urlopen",
        lambda request, timeout: FakeReadyResponse(),
    )
    assert ai_live_eval.check_readiness("http://test", timeout_s=1)["ready"] is True

    monkeypatch.setattr(
        "scripts.ai_live_eval.urlopen",
        lambda request, timeout: (_ for _ in ()).throw(URLError("down")),
    )
    assert ai_live_eval.check_readiness("http://test", timeout_s=1)["ready"] is False


def test_live_ai_eval_report_compares_captures_to_synthetic_labels(monkeypatch):
    synthetic_events = {scenario.name: scenario.events for scenario in ai_eval.build_scenarios()}

    def fake_run_live_scenario(base_url, scenario, *, timeout_s):
        return captures_from_events(scenario.name, synthetic_events[scenario.name])

    monkeypatch.setattr(ai_live_eval, "run_live_scenario", fake_run_live_scenario)

    report = ai_live_eval.run_live_evaluation(
        base_url="http://test",
        generated_at=123,
        run_id="test",
        scenario_names={"normal-free-traffic", "abusive-identifier", "route-spike"},
        skip_readiness=True,
    )

    assert report["schema_version"] == 1
    assert report["summary"]["live_scenarios"] == 3
    assert report["summary"]["stable_live_scenarios"] == 3
    assert report["summary"]["synthetic_matches"] == 3
    assert report["summary"]["synthetic_agreement"] == "matched"
    scenarios = {item["name"]: item for item in report["scenarios"]}
    assert scenarios["normal-free-traffic"]["matches_synthetic_observed"] is True
    assert scenarios["abusive-identifier"]["recommendations"]["observed"] == ["abuse"]
    assert scenarios["route-spike"]["anomalies"]["observed"] == ["route_traffic_spike"]


def test_live_ai_eval_marks_capture_errors_for_review():
    scenario = ai_live_eval.LiveScenario(
        name="normal-free-traffic",
        description="error case",
        requests=[("/api/data", "user")],
    )
    captures = [
        ai_live_eval.CapturedResponse(
            scenario=scenario.name,
            endpoint="/api/data",
            api_key="user",
            timestamp=123.0,
            status="error",
            latency_ms=1.0,
            headers={},
            error="connection refused",
        )
    ]

    result = ai_live_eval.evaluate_live_captures(
        scenario,
        captures,
        generated_at=123,
        synthetic_result={
            "recommendations": {"observed": []},
            "anomalies": {"observed": []},
        },
        scenario_definition=ai_eval.build_scenarios()[0],
    )

    assert result["capture"]["errors"] == 1
    assert result["events_evaluated"] == 0
    assert result["matches_synthetic_observed"] is False
    assert result["policy_stability"] == "review"


def test_live_ai_eval_main_writes_optional_report(monkeypatch, capsys):
    output_path = Path("tmp-test-data") / "ai-live-eval-test-report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)

    def fake_run_live_evaluation(**kwargs):
        return {
            "schema_version": 1,
            "generated_at": 123,
            "base_url": kwargs["base_url"],
            "readiness": {"ready": None, "skipped": True},
            "summary": {"live_scenarios": 0},
            "scenarios": [],
            "limitations": [],
        }

    monkeypatch.setattr(ai_live_eval, "run_live_evaluation", fake_run_live_evaluation)

    original_argv = sys.argv
    sys.argv = [
        "ai_live_eval.py",
        "--base-url",
        "http://test",
        "--output",
        str(output_path),
        "--skip-readiness",
    ]
    try:
        ai_live_eval.main()
    finally:
        sys.argv = original_argv

    captured = capsys.readouterr()
    printed = json.loads(captured.out)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert printed["base_url"] == "http://test"
    assert written == printed
    output_path.unlink(missing_ok=True)

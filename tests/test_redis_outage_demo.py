from argparse import Namespace

from scripts import redis_outage_demo


def test_compose_args_build_stop_and_start_commands():
    assert redis_outage_demo.compose_args("docker compose", "stop", "redis") == [
        "docker",
        "compose",
        "stop",
        "redis",
    ]
    assert redis_outage_demo.compose_args("docker-compose", "start", "redis") == [
        "docker-compose",
        "up",
        "-d",
        "redis",
    ]


def test_summarize_reports_outage_expectation_matches():
    summary = redis_outage_demo.summarize([
        {
            "phase": "during-outage",
            "name": "fail-open",
            "expected_status": 200,
            "observed_status": 200,
            "matched": True,
        },
        {
            "phase": "during-outage",
            "name": "fail-closed",
            "expected_status": 429,
            "observed_status": 429,
            "matched": True,
        },
    ])

    assert summary == {
        "during_outage_checks": 2,
        "matched_expectations": 2,
        "fail_open_status": 200,
        "fail_closed_status": 429,
    }


def test_run_demo_supports_skip_stop_without_docker(monkeypatch):
    def fake_read_response(url, api_key=None, timeout=5.0):
        if url.endswith("/ready"):
            return {"status": 503 if api_key is None else 200}
        if url.endswith("/api/data"):
            return {"status": 200}
        if url.endswith("/api/limited-health"):
            return {"status": 429}
        return {"status": "error"}

    monkeypatch.setattr(redis_outage_demo, "read_response", fake_read_response)

    result = redis_outage_demo.run_demo(
        Namespace(
            base_url="http://test",
            compose_command="docker compose",
            redis_service="redis",
            settle_seconds=0,
            restore_seconds=0,
            skip_stop=True,
            skip_restore=True,
        )
    )

    assert result["managed_outage"] is False
    assert result["commands"] == []
    assert result["summary"]["matched_expectations"] == 2

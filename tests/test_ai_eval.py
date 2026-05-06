import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from app.observability.telemetry_store import SQLiteTelemetryStore
from scripts import ai_eval


def test_ai_eval_scenarios_cover_research_cases():
    scenario_names = {scenario.name for scenario in ai_eval.build_scenarios()}

    assert {
        "normal-free-traffic",
        "premium-burst",
        "abusive-identifier",
        "retry-loop",
        "route-spike",
        "sensitive-route-probing",
        "redis-outage-exposure",
        "fixed-window-pressure",
        "mixed-workload",
    }.issubset(scenario_names)


def test_ai_eval_report_is_deterministic_and_tracks_expected_labels():
    report = ai_eval.run_evaluation(generated_at=123)

    assert report["schema_version"] == 1
    assert report["generated_at"] == 123
    assert report["summary"]["policy_stability"] == "stable"
    assert report["summary"]["recommendation_precision"] == 1.0
    assert report["summary"]["recommendation_recall"] == 1.0
    assert report["summary"]["anomaly_precision"] == 1.0
    assert report["summary"]["anomaly_recall"] == 1.0
    assert report["summary"]["false_positive_notes"] == []

    scenarios = {item["name"]: item for item in report["scenarios"]}
    assert scenarios["premium-burst"]["recommendations"]["observed"] == []
    assert scenarios["premium-burst"]["anomalies"]["observed"] == []
    assert scenarios["abusive-identifier"]["recommendations"]["observed"] == ["abuse"]
    assert scenarios["abusive-identifier"]["anomalies"]["observed"] == [
        "concentrated_offender",
        "retry_loop",
    ]
    assert scenarios["redis-outage-exposure"]["recommendations"]["observed"] == [
        "reliability"
    ]
    assert scenarios["fixed-window-pressure"]["recommendations"]["observed"] == [
        "algorithm",
        "tuning",
    ]


def test_ai_eval_estimates_denied_legitimate_and_abuse_reduction():
    report = ai_eval.run_evaluation(generated_at=123)

    assert report["summary"]["denied_legitimate_estimate"] > 0
    assert report["summary"]["abuse_reduction_estimate"] > 0
    scenarios = {item["name"]: item for item in report["scenarios"]}
    assert scenarios["abusive-identifier"]["denied_legitimate_estimate"] == 0
    assert scenarios["fixed-window-pressure"]["denied_legitimate_estimate"] == 10


def test_ai_eval_main_writes_optional_report(capsys):
    output_path = Path("tmp-test-data") / "ai-eval-test-report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)

    original_argv = sys.argv
    sys.argv = ["ai_eval.py", "--output", str(output_path)]
    try:
        ai_eval.main()
    finally:
        sys.argv = original_argv

    captured = capsys.readouterr()
    printed = json.loads(captured.out)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert printed["summary"]["policy_stability"] == "stable"
    assert written == printed
    output_path.unlink(missing_ok=True)


def test_ai_eval_loads_persisted_events_in_chronological_order():
    db_path = Path("tmp-test-data") / "telemetry" / f"{uuid4()}-ai-eval.sqlite3"
    store = SQLiteTelemetryStore(str(db_path))
    old = ai_eval.event(timestamp=100, identifier="old")
    kept_a = ai_eval.event(timestamp=200, identifier="kept_a")
    kept_b = ai_eval.event(timestamp=300, identifier="kept_b", allowed=False)
    store.record(old)
    store.record(kept_a)
    store.record(kept_b)

    events = ai_eval.load_persisted_events(str(db_path), since=150, until=350, limit=10)

    assert [event.identifier for event in events] == ["kept_a", "kept_b"]
    assert events[1].allowed is False


def test_ai_eval_persistent_window_reports_observed_labels_without_expectations():
    db_path = Path("tmp-test-data") / "telemetry" / f"{uuid4()}-ai-eval-observed.sqlite3"
    store = SQLiteTelemetryStore(str(db_path))
    for event in ai_eval.abusive_identifier_events(1_000):
        store.record(event)

    report = ai_eval.run_persistent_evaluation(
        db_path=str(db_path),
        generated_at=123,
        window_name="demo-window",
    )

    assert report["mode"] == "persistent_window"
    assert report["source"]["telemetry_db"] == str(db_path)
    assert report["summary"]["events"] == 10
    assert report["summary"]["denied"] == 7
    assert report["summary"]["observed_recommendations"] == ["abuse"]
    assert report["summary"]["observed_anomalies"] == [
        "concentrated_offender",
        "retry_loop",
    ]
    assert report["scenarios"][0]["has_expectations"] is False


def test_ai_eval_persistent_window_can_compare_with_expected_scenario():
    db_path = Path("tmp-test-data") / "telemetry" / f"{uuid4()}-ai-eval-expected.sqlite3"
    store = SQLiteTelemetryStore(str(db_path))
    for event in ai_eval.fixed_window_pressure_events(1_000):
        store.record(event)

    report = ai_eval.run_persistent_evaluation(
        db_path=str(db_path),
        generated_at=123,
        expected_scenario="fixed-window-pressure",
    )

    assert report["summary"]["policy_stability"] == "stable"
    assert report["summary"]["recommendation_precision"] == 1.0
    assert report["summary"]["recommendation_recall"] == 1.0
    assert report["scenarios"][0]["has_expectations"] is True
    assert report["scenarios"][0]["recommendations"]["observed"] == [
        "algorithm",
        "tuning",
    ]


def test_ai_eval_persistent_window_rejects_unknown_expected_scenario():
    with pytest.raises(ValueError, match="Unknown expected scenario"):
        ai_eval.run_persistent_evaluation(
            db_path="tmp-test-data/not-used.sqlite3",
            expected_scenario="does-not-exist",
        )


def test_ai_eval_main_writes_persisted_report(capsys):
    db_path = Path("tmp-test-data") / "telemetry" / f"{uuid4()}-ai-eval-main.sqlite3"
    output_path = Path("tmp-test-data") / "ai-eval-persistent-report.json"
    output_path.unlink(missing_ok=True)
    store = SQLiteTelemetryStore(str(db_path))
    for event in ai_eval.normal_free_events(1_000):
        store.record(event)

    original_argv = sys.argv
    sys.argv = [
        "ai_eval.py",
        "--telemetry-db",
        str(db_path),
        "--output",
        str(output_path),
        "--window-name",
        "local-demo",
    ]
    try:
        ai_eval.main()
    finally:
        sys.argv = original_argv

    captured = capsys.readouterr()
    printed = json.loads(captured.out)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert printed["mode"] == "persistent_window"
    assert printed["scenarios"][0]["name"] == "local-demo"
    assert written == printed
    output_path.unlink(missing_ok=True)

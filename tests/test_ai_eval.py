import json
import sys
from pathlib import Path

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

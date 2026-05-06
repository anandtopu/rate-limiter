import json
import sys
from pathlib import Path

from scripts import ai_eval, ai_research_report


def live_report(*, include_outage=False):
    scenarios = [
        {
            "name": "normal-free-traffic",
            "policy_stability": "stable",
            "matches_synthetic_observed": True,
            "capture": {"requests": 10, "redis_fail_open": 0},
            "recommendations": {"observed": []},
            "anomalies": {"observed": []},
            "events_evaluated": 10,
        }
    ]
    outage_runs = []
    if include_outage:
        scenarios.append({
            "name": "redis-outage-exposure",
            "policy_stability": "stable",
            "matches_synthetic_observed": True,
            "capture": {"requests": 2, "redis_fail_open": 2},
            "recommendations": {"observed": ["reliability"]},
            "anomalies": {"observed": ["redis_outage_exposure"]},
            "events_evaluated": 2,
        })
        outage_runs.append({"managed_outage": True, "restored": True})

    return {
        "schema_version": 1,
        "summary": {
            "live_scenarios": len(scenarios),
            "stable_live_scenarios": len(scenarios),
            "synthetic_matches": len(scenarios),
            "synthetic_agreement": "matched",
        },
        "scenarios": scenarios,
        "outage_runs": outage_runs,
        "limitations": ["Live report limitation."],
    }


def test_ai_research_report_combines_all_report_sections():
    report = ai_research_report.build_research_report(
        synthetic_report=ai_eval.run_evaluation(generated_at=123),
        live_report=live_report(),
        outage_report=live_report(include_outage=True),
        persisted_report=ai_eval.run_persistent_evaluation(
            db_path=create_persisted_db("fixed-window-pressure"),
            generated_at=123,
            expected_scenario="fixed-window-pressure",
        ),
    )

    assert report["schema_version"] == 1
    assert report["summary"]["overall_status"] == "stable"
    assert report["summary"]["sections_provided"] == 4
    sections = {section["kind"]: section for section in report["sections"]}
    assert sections["synthetic"]["metrics"]["recommendation_precision"] == 1.0
    assert sections["live"]["metrics"]["synthetic_agreement"] == "matched"
    assert sections["outage"]["metrics"]["redis_fail_open"] == 2
    assert sections["persisted"]["metrics"]["recommendation_precision"] == 1.0


def test_ai_research_report_marks_missing_optional_sections():
    report = ai_research_report.build_research_report(
        synthetic_report=ai_eval.run_evaluation(generated_at=123)
    )

    assert report["summary"]["overall_status"] == "stable"
    assert report["summary"]["sections_provided"] == 1
    sections = {section["kind"]: section for section in report["sections"]}
    assert sections["live"]["status"] == "not_provided"
    assert sections["outage"]["status"] == "not_provided"
    assert sections["persisted"]["status"] == "not_provided"


def test_ai_research_report_marks_review_when_a_section_needs_review():
    report = ai_research_report.build_research_report(
        synthetic_report=ai_eval.run_evaluation(generated_at=123),
        live_report={
            "summary": {
                "live_scenarios": 1,
                "stable_live_scenarios": 0,
                "synthetic_matches": 0,
                "synthetic_agreement": "review",
            },
            "limitations": [],
        },
    )

    assert report["summary"]["overall_status"] == "review"
    assert report["summary"]["sections"]["live"] == "review"


def test_ai_research_report_renders_markdown():
    report = ai_research_report.build_research_report(
        synthetic_report=ai_eval.run_evaluation(generated_at=123),
        live_report=live_report(),
    )

    markdown = ai_research_report.render_markdown(report)

    assert "# AI Rate Limiter Research Report" in markdown
    assert "## Synthetic Baseline" in markdown
    assert "recommendation_precision" in markdown
    assert "## Live HTTP Comparison" in markdown


def test_ai_research_report_main_writes_markdown_and_json(monkeypatch, capsys):
    output_path = Path("tmp-test-data") / "ai-research-report.md"
    json_output_path = Path("tmp-test-data") / "ai-research-report.json"
    output_path.unlink(missing_ok=True)
    json_output_path.unlink(missing_ok=True)

    original_argv = sys.argv
    sys.argv = [
        "ai_research_report.py",
        "--output",
        str(output_path),
        "--json-output",
        str(json_output_path),
    ]
    try:
        ai_research_report.main()
    finally:
        sys.argv = original_argv

    captured = capsys.readouterr()
    assert "AI Rate Limiter Research Report" in captured.out
    assert output_path.read_text(encoding="utf-8") == captured.out
    machine_report = json.loads(json_output_path.read_text(encoding="utf-8"))
    assert machine_report["summary"]["sections"]["synthetic"] == "stable"
    output_path.unlink(missing_ok=True)
    json_output_path.unlink(missing_ok=True)


def create_persisted_db(scenario_name="normal-free-traffic"):
    from uuid import uuid4

    from app.observability.telemetry_store import SQLiteTelemetryStore

    db_path = Path("tmp-test-data") / "telemetry" / f"{uuid4()}-research.sqlite3"
    store = SQLiteTelemetryStore(str(db_path))
    scenario = next(
        item for item in ai_eval.build_scenarios() if item.name == scenario_name
    )
    for event in scenario.events:
        store.record(event)
    return str(db_path)

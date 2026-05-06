import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from scripts import ai_ci_dry_run


def test_ai_ci_dry_run_writes_local_artifacts_without_live_services():
    output_dir = Path("tmp-test-data") / "ai-ci-dry-run-tests" / str(uuid4())

    summary = ai_ci_dry_run.run_ci_dry_run(output_dir=output_dir, generated_at=123)

    assert summary["mode"] == "ci_dry_run"
    assert summary["docker_required"] is False
    assert summary["redis_required"] is False
    assert summary["persisted_fixture"]["scenario"] == "fixed-window-pressure"
    assert summary["persisted_fixture"]["events_seeded"] == 25
    assert summary["summary"]["synthetic_policy_stability"] == "stable"
    assert summary["summary"]["persisted_policy_stability"] == "stable"
    assert summary["summary"]["research_overall_status"] == "stable"

    artifacts = summary["artifacts"]
    for path in artifacts.values():
        assert Path(path).exists()
    assert Path(summary["persisted_fixture"]["telemetry_db"]).exists()

    manifest = json.loads((output_dir / "manifest.json").read_text("utf-8"))
    assert manifest["kind"] == "rate-limiter.ai-ci-dry-run.manifest"
    assert manifest["status"] == "stable"
    assert manifest["docker_required"] is False
    assert manifest["redis_required"] is False
    assert manifest["recommended_entrypoints"] == [
        "MANIFEST.md",
        "AI_RESEARCH_REPORT.md",
        "summary.json",
    ]
    assert manifest["summary"]["research_sections_provided"] == 2
    manifest_artifacts = {item["name"]: item for item in manifest["artifacts"]}
    assert manifest_artifacts["synthetic_json"]["status"] == "stable"
    assert manifest_artifacts["persisted_json"]["status"] == "stable"
    assert manifest_artifacts["research_markdown"]["relative_path"] == (
        "AI_RESEARCH_REPORT.md"
    )
    assert manifest_artifacts["summary_json"]["status"] == "available"
    assert manifest_artifacts["telemetry_db"]["bytes"] > 0
    assert "AI CI Dry Run Artifact Manifest" in (output_dir / "MANIFEST.md").read_text(
        "utf-8"
    )

    persisted = json.loads(Path(artifacts["persisted_json"]).read_text("utf-8"))
    assert persisted["source"]["expected_scenario"] == "fixed-window-pressure"
    assert persisted["scenarios"][0]["name"] == "ci-fixed-window-pressure"
    assert "AI Rate Limiter Research Report" in Path(
        artifacts["research_markdown"]
    ).read_text("utf-8")


def test_ai_ci_dry_run_rejects_unknown_persisted_scenario():
    with pytest.raises(ValueError, match="Unknown persisted scenario"):
        ai_ci_dry_run.run_ci_dry_run(
            output_dir=Path("tmp-test-data") / "unused-ci-dry-run",
            persisted_scenario="missing-scenario",
        )


def test_ai_ci_dry_run_lists_available_scenarios():
    scenarios = ai_ci_dry_run.scenario_index()

    scenario_names = {scenario["name"] for scenario in scenarios}
    assert "fixed-window-pressure" in scenario_names
    fixed_window = next(
        scenario for scenario in scenarios if scenario["name"] == "fixed-window-pressure"
    )
    assert fixed_window["events"] == 25
    assert fixed_window["expected_recommendations"] == ["algorithm", "tuning"]


def test_ai_ci_dry_run_main_prints_summary(capsys):
    output_dir = Path("tmp-test-data") / "ai-ci-dry-run-tests" / str(uuid4())
    original_argv = sys.argv
    sys.argv = [
        "ai_ci_dry_run.py",
        "--output-dir",
        str(output_dir),
        "--persisted-scenario",
        "normal-free-traffic",
    ]
    try:
        ai_ci_dry_run.main()
    finally:
        sys.argv = original_argv

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["persisted_fixture"]["scenario"] == "normal-free-traffic"
    assert summary["persisted_fixture"]["events_seeded"] == 10
    assert Path(summary["artifacts"]["manifest_json"]).exists()
    assert Path(summary["artifacts"]["manifest_markdown"]).exists()
    assert json.loads((output_dir / "summary.json").read_text("utf-8")) == summary


def test_ai_ci_dry_run_main_can_list_scenarios(capsys):
    original_argv = sys.argv
    sys.argv = ["ai_ci_dry_run.py", "--list-scenarios"]
    try:
        ai_ci_dry_run.main()
    finally:
        sys.argv = original_argv

    scenarios = json.loads(capsys.readouterr().out)
    assert any(scenario["name"] == "normal-free-traffic" for scenario in scenarios)

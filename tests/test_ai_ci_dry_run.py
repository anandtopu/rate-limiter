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
    assert json.loads((output_dir / "summary.json").read_text("utf-8")) == summary

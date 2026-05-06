# ruff: noqa: E402,I001
import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.observability.telemetry_store import SQLiteTelemetryStore  # noqa: E402
from scripts import ai_eval, ai_research_report  # noqa: E402


DEFAULT_OUTPUT_DIR = Path("tmp-test-data") / "ai-ci-dry-run"
DEFAULT_PERSISTED_SCENARIO = "fixed-window-pressure"


def write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(report, indent=2)}\n", encoding="utf-8")


def scenario_by_name(name: str) -> ai_eval.EvaluationScenario:
    scenarios = {scenario.name: scenario for scenario in ai_eval.build_scenarios()}
    if name not in scenarios:
        choices = ", ".join(sorted(scenarios))
        raise ValueError(f"Unknown persisted scenario: {name}. Choices: {choices}")
    return scenarios[name]


def reset_sqlite_artifacts(db_path: Path) -> None:
    for path in [
        db_path,
        db_path.parent / f"{db_path.name}-wal",
        db_path.parent / f"{db_path.name}-shm",
    ]:
        path.unlink(missing_ok=True)


def seed_persisted_fixture(*, db_path: Path, scenario_name: str) -> int:
    scenario = scenario_by_name(scenario_name)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    reset_sqlite_artifacts(db_path)
    store = SQLiteTelemetryStore(str(db_path))
    for event in scenario.events:
        store.record(event)
    return len(scenario.events)


def run_ci_dry_run(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    persisted_scenario: str = DEFAULT_PERSISTED_SCENARIO,
    generated_at: int = 1_734_000_000,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    synthetic_report = ai_eval.run_evaluation(generated_at=generated_at)
    synthetic_path = output_dir / "ai-eval-synthetic.json"
    write_json(synthetic_path, synthetic_report)

    telemetry_db_path = output_dir / "telemetry.sqlite3"
    events_seeded = seed_persisted_fixture(
        db_path=telemetry_db_path,
        scenario_name=persisted_scenario,
    )
    persisted_report = ai_eval.run_persistent_evaluation(
        db_path=str(telemetry_db_path),
        expected_scenario=persisted_scenario,
        generated_at=generated_at,
        window_name=f"ci-{persisted_scenario}",
    )
    persisted_path = output_dir / "ai-eval-persisted.json"
    write_json(persisted_path, persisted_report)

    research_report = ai_research_report.build_research_report(
        synthetic_report=synthetic_report,
        persisted_report=persisted_report,
    )
    research_json_path = output_dir / "ai-research-report.json"
    write_json(research_json_path, research_report)

    research_markdown_path = output_dir / "AI_RESEARCH_REPORT.md"
    research_markdown_path.write_text(
        ai_research_report.render_markdown(research_report),
        encoding="utf-8",
    )

    summary = {
        "schema_version": 1,
        "mode": "ci_dry_run",
        "output_dir": str(output_dir),
        "docker_required": False,
        "redis_required": False,
        "persisted_fixture": {
            "scenario": persisted_scenario,
            "events_seeded": events_seeded,
            "telemetry_db": str(telemetry_db_path),
        },
        "summary": {
            "synthetic_policy_stability": synthetic_report["summary"][
                "policy_stability"
            ],
            "persisted_policy_stability": persisted_report["summary"][
                "policy_stability"
            ],
            "research_overall_status": research_report["summary"]["overall_status"],
            "research_sections_provided": research_report["summary"][
                "sections_provided"
            ],
        },
        "artifacts": {
            "synthetic_json": str(synthetic_path),
            "persisted_json": str(persisted_path),
            "research_json": str(research_json_path),
            "research_markdown": str(research_markdown_path),
        },
        "limitations": [
            "This dry run uses deterministic in-process events and a local SQLite fixture.",
            "It does not start the FastAPI app, Redis, Docker Compose, or the live HTTP evaluator.",
            "Use scripts/ai_live_eval.py for end-to-end Redis-backed behavior.",
        ],
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run CI-friendly AI eval dry runs without Docker, Redis, or a live app."
        )
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated JSON, SQLite fixture, and Markdown artifacts.",
    )
    parser.add_argument(
        "--persisted-scenario",
        default=DEFAULT_PERSISTED_SCENARIO,
        help="Synthetic scenario used to seed the local persisted telemetry fixture.",
    )
    parser.add_argument(
        "--generated-at",
        type=int,
        default=1_734_000_000,
        help="Deterministic timestamp used in generated reports.",
    )
    args = parser.parse_args()

    summary = run_ci_dry_run(
        output_dir=Path(args.output_dir),
        persisted_scenario=args.persisted_scenario,
        generated_at=args.generated_at,
    )
    sys.stdout.write(f"{json.dumps(summary, indent=2)}\n")


if __name__ == "__main__":
    main()

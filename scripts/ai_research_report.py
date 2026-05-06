# ruff: noqa: E402,I001
import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.ai_eval import run_evaluation  # noqa: E402


SECTION_ORDER = ["synthetic", "live", "outage", "persisted"]


def load_json_report(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def status_from_value(value: str | None) -> str:
    if value in {"stable", "matched"}:
        return "stable"
    if value is None:
        return "not_provided"
    return "review"


def summarize_synthetic(report: dict[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {
            "kind": "synthetic",
            "title": "Synthetic Baseline",
            "status": "not_provided",
            "metrics": {},
            "notes": ["Synthetic baseline was not included."],
        }

    summary = report.get("summary", {})
    return {
        "kind": "synthetic",
        "title": "Synthetic Baseline",
        "status": status_from_value(summary.get("policy_stability")),
        "metrics": {
            "scenarios": summary.get("scenarios"),
            "stable_scenarios": summary.get("stable_scenarios"),
            "recommendation_precision": summary.get("recommendation_precision"),
            "recommendation_recall": summary.get("recommendation_recall"),
            "anomaly_precision": summary.get("anomaly_precision"),
            "anomaly_recall": summary.get("anomaly_recall"),
            "denied_legitimate_estimate": summary.get("denied_legitimate_estimate"),
            "abuse_reduction_estimate": summary.get("abuse_reduction_estimate"),
        },
        "notes": report.get("limitations", []),
    }


def summarize_live(report: dict[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {
            "kind": "live",
            "title": "Live HTTP Comparison",
            "status": "not_provided",
            "metrics": {},
            "notes": ["Live HTTP comparison JSON was not supplied."],
        }

    summary = report.get("summary", {})
    return {
        "kind": "live",
        "title": "Live HTTP Comparison",
        "status": status_from_value(summary.get("synthetic_agreement")),
        "metrics": {
            "live_scenarios": summary.get("live_scenarios"),
            "stable_live_scenarios": summary.get("stable_live_scenarios"),
            "synthetic_matches": summary.get("synthetic_matches"),
            "synthetic_agreement": summary.get("synthetic_agreement"),
        },
        "notes": report.get("limitations", []),
    }


def summarize_outage(report: dict[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {
            "kind": "outage",
            "title": "Redis Outage Live Coverage",
            "status": "not_provided",
            "metrics": {},
            "notes": ["Redis outage live comparison JSON was not supplied."],
        }

    scenarios = {
        item.get("name"): item
        for item in report.get("scenarios", [])
        if isinstance(item, dict)
    }
    outage = scenarios.get("redis-outage-exposure")
    status = "not_provided"
    metrics: dict[str, Any] = {}
    notes = list(report.get("limitations", []))
    if outage:
        status = status_from_value(outage.get("policy_stability"))
        metrics = {
            "events_evaluated": outage.get("events_evaluated"),
            "redis_fail_open": (outage.get("capture") or {}).get("redis_fail_open"),
            "recommendations": outage.get("recommendations", {}).get("observed"),
            "anomalies": outage.get("anomalies", {}).get("observed"),
            "matches_synthetic": outage.get("matches_synthetic_observed"),
        }
    else:
        notes.append("Report did not include redis-outage-exposure.")

    return {
        "kind": "outage",
        "title": "Redis Outage Live Coverage",
        "status": status,
        "metrics": metrics,
        "notes": notes,
    }


def summarize_persisted(report: dict[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {
            "kind": "persisted",
            "title": "Persisted Telemetry Replay",
            "status": "not_provided",
            "metrics": {},
            "notes": ["Persisted telemetry replay JSON was not supplied."],
        }

    summary = report.get("summary", {})
    if "policy_stability" in summary:
        status = status_from_value(summary.get("policy_stability"))
        metrics = {
            "scenarios": summary.get("scenarios"),
            "stable_scenarios": summary.get("stable_scenarios"),
            "recommendation_precision": summary.get("recommendation_precision"),
            "recommendation_recall": summary.get("recommendation_recall"),
            "anomaly_precision": summary.get("anomaly_precision"),
            "anomaly_recall": summary.get("anomaly_recall"),
        }
    else:
        status = status_from_value(summary.get("policy_stability"))
        metrics = {
            "events": summary.get("events"),
            "denied": summary.get("denied"),
            "observed_recommendations": summary.get("observed_recommendations"),
            "observed_anomalies": summary.get("observed_anomalies"),
        }

    return {
        "kind": "persisted",
        "title": "Persisted Telemetry Replay",
        "status": status,
        "metrics": metrics,
        "notes": report.get("limitations", []),
    }


def overall_status(sections: list[dict[str, Any]]) -> str:
    provided = [section for section in sections if section["status"] != "not_provided"]
    if not provided:
        return "not_provided"
    if all(section["status"] == "stable" for section in provided):
        return "stable"
    return "review"


def build_research_report(
    *,
    synthetic_report: dict[str, Any] | None,
    live_report: dict[str, Any] | None = None,
    outage_report: dict[str, Any] | None = None,
    persisted_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sections = [
        summarize_synthetic(synthetic_report),
        summarize_live(live_report),
        summarize_outage(outage_report),
        summarize_persisted(persisted_report),
    ]
    return {
        "schema_version": 1,
        "summary": {
            "overall_status": overall_status(sections),
            "sections_provided": sum(
                1 for section in sections if section["status"] != "not_provided"
            ),
            "sections": {
                section["kind"]: section["status"]
                for section in sorted(
                    sections,
                    key=lambda section: SECTION_ORDER.index(section["kind"]),
                )
            },
        },
        "sections": sections,
    }


def _format_metric_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "none"
    if value is None:
        return "n/a"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AI Rate Limiter Research Report",
        "",
        "## Summary",
        "",
        f"- Overall status: `{report['summary']['overall_status']}`",
        f"- Sections provided: `{report['summary']['sections_provided']}`",
        "",
    ]

    for section in report["sections"]:
        lines.extend([
            f"## {section['title']}",
            "",
            f"- Status: `{section['status']}`",
        ])
        for key, value in section["metrics"].items():
            lines.append(f"- {key}: `{_format_metric_value(value)}`")
        if section["notes"]:
            lines.append("")
            lines.append("Notes:")
            for note in section["notes"]:
                lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a compact AI research report artifact."
    )
    parser.add_argument(
        "--synthetic-json",
        help="Optional precomputed synthetic ai_eval JSON. Defaults to a fresh run.",
    )
    parser.add_argument("--live-json", help="Optional live ai_live_eval JSON.")
    parser.add_argument("--outage-json", help="Optional live outage ai_live_eval JSON.")
    parser.add_argument("--persisted-json", help="Optional persisted ai_eval JSON.")
    parser.add_argument(
        "--no-synthetic",
        action="store_true",
        help="Do not run or load the synthetic baseline.",
    )
    parser.add_argument(
        "--output",
        default="docs/AI_RESEARCH_REPORT.md",
        help="Markdown report path.",
    )
    parser.add_argument("--json-output", help="Optional machine-readable report path.")
    args = parser.parse_args()

    synthetic_report = None
    if not args.no_synthetic:
        synthetic_report = (
            load_json_report(args.synthetic_json)
            if args.synthetic_json
            else run_evaluation()
        )

    report = build_research_report(
        synthetic_report=synthetic_report,
        live_report=load_json_report(args.live_json),
        outage_report=load_json_report(args.outage_json),
        persisted_report=load_json_report(args.persisted_json),
    )
    rendered = render_markdown(report)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    if args.json_output:
        json_output_path = Path(args.json_output)
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        json_output_path.write_text(
            f"{json.dumps(report, indent=2)}\n",
            encoding="utf-8",
        )

    sys.stdout.write(rendered)


if __name__ == "__main__":
    main()

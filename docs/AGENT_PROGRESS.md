# Agent Progress Tracker

Last updated: 2026-05-06

## Current Runtime

- App URL: `http://localhost:8001`
- Demo dashboard: `http://localhost:8001/demo`
- Redis host port: `localhost:6378`
- Container Redis port: `6379`
- Admin header: `X-Admin-Key: dev-admin-key`

## Environment Notes

- Local Python was repaired with uv-managed Python 3.11.15.
- Use `.venv\Scripts\python.exe`, `.venv\Scripts\pytest.exe`, and `.venv\Scripts\ruff.exe`.
- Security tooling is installed in the local venv; Bandit runs locally, while `pip-audit -r requirements.txt` was verified in the Linux container because this Windows sandbox blocks pip-audit's temporary resolver venv.
- Docker access may require elevated permissions in this environment.
- Ignore locked local scratch folders; `.dockerignore` and `.gitignore` exclude them.
- Use `docker-compose` if `docker compose` is not available in the current shell.
- `git status --short` may print `unable to access 'C:\Users\anand/.config/git/ignore': Permission denied`; this is a user-level ignore warning, not a repo change.

## Resume Snapshot

- Saved for resume on 2026-05-05.
- Worktree contains cumulative uncommitted backlog changes from the current implementation pass.
- The original portfolio upgrade is complete through Phase 35.
- The forward backlog has been refreshed as an AI research upgrade in [AI_RESEARCH_ROADMAP.md](AI_RESEARCH_ROADMAP.md), [BACKLOG_STATUS.md](BACKLOG_STATUS.md), and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
- Latest known verification from this coding pass:
  - `.\.venv\Scripts\ruff.exe check .` passed.
  - `.\.venv\Scripts\pytest.exe -q` passed with `145 passed`.
  - `.\.venv\Scripts\pytest.exe --cov=app --cov=scripts --cov-report=term-missing --cov-report=xml` passed with `145 passed`, `86%` total coverage, and `coverage.xml` generated.
  - `.\.venv\Scripts\python.exe scripts\ai_eval.py` passed with 9 scenarios, 9 stable scenarios, recommendation precision `1.0`, recommendation recall `1.0`, anomaly precision `1.0`, and anomaly recall `1.0`.
  - `.\.venv\Scripts\python.exe scripts\ai_eval.py --help` passed and shows persisted telemetry replay flags.
  - `.\.venv\Scripts\python.exe scripts\ai_live_eval.py --help` passed.
  - `.\.venv\Scripts\python.exe scripts\ai_research_report.py --output docs\AI_RESEARCH_REPORT.md` passed.
  - `.\.venv\Scripts\python.exe scripts\ai_ci_dry_run.py --output-dir tmp-test-data\ai-ci-dry-run` passed.
  - `.\.venv\Scripts\python.exe scripts\dashboard_screenshots.py --base-url http://localhost:8001` passed with `status: skipped` because Playwright is not installed in this local environment.
- The AI research queue is complete through AI-P5.
- The first twenty-four post-AI-P5 follow-ups are complete through AI-H24.
- Recommended first implementation read:
  - [app/core/rules.py](../app/core/rules.py)
  - [app/api/admin.py](../app/api/admin.py)
  - [app/models/rules.py](../app/models/rules.py)
  - [app/static/demo.js](../app/static/demo.js)
  - [tests/test_admin.py](../tests/test_admin.py)

## Completed Phases

| Phase | Status | Summary |
| --- | --- | --- |
| 0 | Done | README positioning, architecture notes, baseline verification notes. |
| 1 | Done | Correct limiter result object, positive rule validation, accurate `Retry-After`. |
| 2 | Done | Admin auth, rule validate/update/reload, AI endpoint protection. |
| 3 | Done | Metrics, readiness, request IDs, structured decision logs, identifier hashing. |
| 4 | Done | Static `/demo` dashboard. |
| 5 | Done | Ruff, CI workflow, `.env.example`, Makefile, load-test script. |
| 6 | Done | Rule version history and rollback. |
| 7 | Done | Policy dry-run endpoint and dashboard panel. |
| 8 | Done | Per-rule algorithms: `token_bucket` and `fixed_window`. |
| 9 | Done | Optional OpenTelemetry request and limiter-decision tracing. |
| 10 | Done | Optional SQLite telemetry persistence and admin inspection endpoint. |
| 11 | Done | README dashboard screenshots for desktop and narrow layouts. |
| 12 | Done | CI dependency audit and static security scanning with vulnerable pins upgraded. |
| 13 | Done | Rule history audit metadata for updates, reloads, and rollbacks. |
| 14 | Done | Optional OpenTelemetry OTLP/HTTP exporter configuration. |
| 15 | Done | Persisted telemetry summaries in the demo dashboard. |
| 16 | Done | Generated CycloneDX SBOM artifact in CI and local developer workflow. |
| 17 | Done | Dashboard controls for audited rule updates, reloads, and rollbacks. |
| 18 | Done | Local OpenTelemetry collector compose profile for tracing demos. |
| 19 | Done | Persistent telemetry time-range filters in the API and dashboard. |
| 20 | Done | Docker Compose health checks for Redis and the web app. |
| 21 | Done | Trusted reverse-proxy policy for `X-Forwarded-For` client identity. |
| 22 | Done | Templated route keys for path-parameter routes. |
| 23 | Done | Rule owner and sensitivity metadata for validation, demo rules, logs, and limiter traces. |
| 24 | Done | Sensitive-rule approval workflow with pending changes and second-admin approval. |
| 25 | Done | Optional SQLite-backed durable rule store while preserving the JSON default path. |
| 26 | Done | Dashboard pending approval panel with approve/reject actions and audit metadata. |
| 27 | Done | Filtered rule-change audit API and dashboard view for route, actor, action, sensitivity, and time range. |
| 28 | Done | Redis outage demo script for fail-open and fail-closed behavior. |
| 29 | Done | Recommendation-to-dry-run flow that drafts editable policy JSON from AI suggestions. |
| 30 | Done | Documented load-test benchmark output for free, premium, abusive, and templated-route scenarios. |
| 31 | Done | CI coverage reporting with terminal summary and uploaded coverage XML artifact. |
| 32 | Done | Sliding-window algorithm behind the existing per-rule algorithm selection. |
| 33 | Done | Multiple named admin keys for local rotation demos, audit attribution, and safe key-name introspection. |
| 34 | Done | Rule import/export helpers for sharing demo policies and restoring known-good demo states. |
| 35 | Done | OpenAPI examples for admin rule management, dry runs, rollback, persistent telemetry filters, and metadata fields. |
| AI-P0 | Done | Enriched telemetry and deterministic route, identifier, and route-identifier feature extraction. |
| AI-P1 | Done | Structured advisor v2 recommendations for tuning, abuse, reliability, and algorithm selection. |
| AI-P2 | Done | Replay-based counterfactual dry-runs with route and identifier impact summaries. |
| AI-P3 | Done | Deterministic anomaly detection for route spikes, retry loops, concentrated offenders, sensitive-route probing, and Redis outage exposure. |
| AI-P4 | Done | Optional policy copilot with disabled-by-default config, fake provider, safe validation, dry-run, and dashboard controls. |
| AI-P5 | Done | Deterministic research evaluation harness with labeled scenarios, precision/recall metrics, false-positive notes, and documented limitations. |
| AI-H1 | Done | Advisor hardening suppresses broad tuning recommendations when denials are dominated by concentrated abuse. |
| AI-H2 | Done | OpenAI-compatible HTTP adapter for the policy copilot with provider errors isolated from config errors and fake-provider tests preserved. |
| AI-H3 | Done | Live HTTP AI evaluation compares Redis-backed response captures with the deterministic synthetic baseline. |
| AI-H4 | Done | Persisted SQLite telemetry windows can be replayed through AI evaluation reports with optional labeled-scenario comparison. |
| AI-H5 | Done | Live AI evaluation can opt into a managed Redis outage to cover the reliability scenario end to end. |
| AI-H6 | Done | Generated Markdown research report artifact combines available synthetic, live, outage, and persisted AI evaluation summaries. |
| AI-H7 | Done | CI-friendly AI dry-run wrapper writes synthetic, seeded persisted, and research-report artifacts without Docker, Redis, or a live app. |
| AI-H8 | Done | Admin API endpoint and dashboard panel expose the latest generated AI research report artifact. |
| AI-H9 | Done | CI runs the AI dry-run wrapper and uploads the generated research artifact bundle. |
| AI-H10 | Done | AI research report endpoint can return raw Markdown and attachment downloads in addition to JSON metadata. |
| AI-H11 | Done | AI CI dry-run bundle includes `MANIFEST.md` and `manifest.json` indexes with artifact paths, statuses, and byte counts. |
| AI-H12 | Done | Dashboard AI Research Report panel can download the raw Markdown artifact with the current admin key. |
| AI-H13 | Done | README documents CI artifact bundle locations and reviewer entrypoints. |
| AI-H14 | Done | Dashboard report download status reports saved filename and byte count. |
| AI-H15 | Done | Dashboard report download uses the server-provided `Content-Disposition` filename. |
| AI-H16 | Done | AI research report JSON metadata includes a canonical `download_url`. |
| AI-H17 | Done | Dashboard JSON view displays the report `download_url`. |
| AI-H18 | Done | `scripts/ai_ci_dry_run.py --list-scenarios` lists seeded persisted replay scenarios. |
| AI-H19 | Done | AI CI manifest tests cover reviewer entrypoints, section counts, and artifact statuses. |
| AI-H20 | Done | README includes a CI artifact quick-reference table for reviewers. |
| AI-H21 | Done | Backlog, roadmap, design, and implementation docs are synchronized for this follow-up batch. |
| AI-H22 | Done | Final verification and generated AI CI artifact refresh completed for the 10-item batch. |
| AI-H23 | Done | Optional dashboard screenshot refresh helper targets the AI Research Report panel and skips cleanly when Playwright is not installed. |
| AI-H24 | Done | CI artifact uploads for coverage, SBOM, and AI dry-run bundles retain artifacts for 30 days. |

## Verification Commands

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\pytest.exe --cov=app --cov=scripts --cov-report=term-missing --cov-report=xml
.\.venv\Scripts\python.exe scripts\ai_eval.py
.\.venv\Scripts\python.exe scripts\ai_eval.py --telemetry-db data/telemetry.sqlite3 --since 1777940000 --limit 500 --window-name local-demo-window
.\.venv\Scripts\python.exe scripts\ai_live_eval.py --base-url http://localhost:8001
.\.venv\Scripts\python.exe scripts\ai_live_eval.py --base-url http://localhost:8001 --include-redis-outage
.\.venv\Scripts\python.exe scripts\ai_research_report.py --output docs\AI_RESEARCH_REPORT.md
.\.venv\Scripts\python.exe scripts\ai_ci_dry_run.py --output-dir tmp-test-data\ai-ci-dry-run
.\.venv\Scripts\python.exe scripts\ai_ci_dry_run.py --list-scenarios
.\.venv\Scripts\python.exe scripts\dashboard_screenshots.py --base-url http://localhost:8001
.\.venv\Scripts\bandit.exe -q -r app -c pyproject.toml
.\.venv\Scripts\cyclonedx-py.exe requirements requirements.txt --of JSON --output-reproducible --output-file sbom.json
docker-compose build web
docker-compose run --rm --no-deps web sh -lc "python -m pip install -r requirements-dev.txt && pip-audit -r requirements.txt --cache-dir .pip-audit-cache && bandit -q -r app -c pyproject.toml && cyclonedx-py requirements requirements.txt --of JSON --output-reproducible --output-file /tmp/sbom.json && test -s /tmp/sbom.json"
docker-compose run --rm --no-deps web pytest -q
docker-compose up -d
.\.venv\Scripts\python.exe scripts\redis_outage_demo.py --base-url http://localhost:8001
```

## Live Smoke Checks

```powershell
curl.exe -s http://localhost:8001/ready
curl.exe -s -i http://localhost:8001/api/data -H "X-API-Key: smoke"
curl.exe -s -i http://localhost:8001/api/limited-health -H "X-API-Key: smoke"
curl.exe -s http://localhost:8001/admin/rules/history -H "X-Admin-Key: dev-admin-key"
curl.exe -s http://localhost:8001/admin/rules/pending -H "X-Admin-Key: dev-admin-key"
curl.exe -s http://localhost:8001/admin/telemetry/persistent -H "X-Admin-Key: dev-admin-key"
```

## Next Recommended Work

No queued AI backlog items remain. Candidate follow-ups should come from new user priorities or future evaluation findings.

# Agent Progress Tracker

Last updated: 2026-05-04

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

## Verification Commands

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\bandit.exe -q -r app -c pyproject.toml
docker-compose build web
docker-compose run --rm --no-deps web sh -lc "python -m pip install -r requirements-dev.txt && pip-audit -r requirements.txt --cache-dir .pip-audit-cache && bandit -q -r app -c pyproject.toml"
docker-compose run --rm --no-deps web pytest -q
docker-compose up -d
```

## Live Smoke Checks

```powershell
curl.exe -s http://localhost:8001/ready
curl.exe -s -i http://localhost:8001/api/data -H "X-API-Key: smoke"
curl.exe -s -i http://localhost:8001/api/limited-health -H "X-API-Key: smoke"
curl.exe -s http://localhost:8001/admin/rules/history -H "X-Admin-Key: dev-admin-key"
curl.exe -s http://localhost:8001/admin/telemetry/persistent -H "X-Admin-Key: dev-admin-key"
```

## Next Recommended Work

1. Add richer audit metadata for rule changes.
2. Add optional OpenTelemetry OTLP exporter configuration.
3. Add richer persisted telemetry summaries in the dashboard.
4. Add generated SBOM artifact in CI.

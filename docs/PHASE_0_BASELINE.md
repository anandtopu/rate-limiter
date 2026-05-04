# Phase 0 Baseline Notes

## Commands Checked

### Local Tests

Command:

```powershell
.\.venv\Scripts\pytest.exe -q
```

Result:

- Blocked before tests could start.
- The existing `.venv` points to `C:\Users\anand\AppData\Local\Programs\Python\Python313\python.exe`.
- That Python executable is missing on this machine.

Suggested fix:

```powershell
Remove-Item -LiteralPath .venv -Recurse -Force
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pytest.exe -q
```

Do not remove the virtual environment automatically unless the owner approves it.

### Docker Compose Config

Command:

```bash
docker compose config
```

Result:

- Compose file parsed successfully.
- Services are:
  - `web`
  - `redis`
- `web` publishes port `8000`.
- `redis` publishes port `6379`.

### Docker Compose Startup

Command:

```bash
docker compose up --build -d
```

Result:

- Blocked because Docker Desktop/daemon was not reachable.
- Error indicated the Windows Docker engine pipe was missing: `//./pipe/docker_engine`.

Suggested fix:

- Start Docker Desktop.
- Re-run:

```bash
docker compose up --build -d
docker compose exec web pytest -q
```

## Phase 0 Documentation Changes

- Repositioned README from "production-ready" to "production-inspired".
- Added architecture flow and core module map.
- Added current known tradeoffs.
- Replaced outdated `docker-compose` commands with `docker compose`.
- Added a current HTTP-based portfolio walkthrough while `/demo` is still planned.
- Removed obsolete `version` key from `docker-compose.yml`.

## Follow-up Verification: 2026-05-04

- Confirmed `docker compose config` parses successfully with fixed host ports:
  - `web`: `8000:8000`
  - `redis`: `6379:6379`
- Rebuilt the web image with `docker compose build web`.
- Ran the current test suite in Docker with `docker compose run --rm --no-deps web pytest -q`.
- Result: `18 passed`.

## Phase 3 Verification: 2026-05-04

- Rechecked the local `.venv` after the Python environment update request.
- Result: `.venv` still points to missing `C:\Users\anand\AppData\Local\Programs\Python\Python313\python.exe` in this workspace.
- Rebuilt the Docker image with `docker compose build web`.
- Ran `docker compose run --rm --no-deps web pytest -q`.
- Result: `24 passed`.

## Phase 4 Verification: 2026-05-04

- Updated the host Redis port to avoid a local conflict.
- Confirmed `docker compose config` publishes:
  - `web`: `8001:8000`
  - `redis`: `6378:6379`
- Added and tested the static `/demo` dashboard.
- Rebuilt the Docker image with `docker compose build web`.
- Ran `docker compose run --rm --no-deps web pytest -q`.
- Result: `28 passed`.

## Phase 5 Verification: 2026-05-04

- Rebuilt `.venv` with uv-managed Python 3.11.15 after the old shim pointed to a missing Python 3.13 executable.
- Installed runtime and dev dependencies with `uv pip install --python .\.venv\Scripts\python.exe -r requirements-dev.txt`.
- Added repo-local lint, CI, environment, Makefile, and load-test artifacts.
- Added `.dockerignore` so local virtualenvs and locked scratch folders are excluded from Docker build context.
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `28 passed`.
- Ran `make lint`.
- Result: passed.
- Ran `make test`.
- Result: `28 passed`.
- Ran `docker compose build web`.
- Result: passed.
- Ran `docker compose run --rm --no-deps web pytest -q`.
- Result: `28 passed`.
- Ran `make load-test` against `http://localhost:8001`.
- Result: free and limited-health scenarios produced `429` responses while premium traffic completed without errors.

## Phase 6 Verification: 2026-05-04

- Added rule version history in adjacent `rules.json.history.json` runtime files.
- Added `GET /admin/rules/history`.
- Added `POST /admin/rules/rollback/{version}`.
- Updated the demo dashboard with a rule history panel.
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `30 passed`.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `30 passed`.
- Restarted the live stack with `docker-compose up -d`.
- Smoke checks:
  - `GET /demo`: `200`
  - `GET /ready`: Redis `ok`
  - `GET /admin/rules/history`: returned current version metadata.

## Phase 7 Verification: 2026-05-04

- Added policy dry-run estimates for proposed rules based on recent telemetry.
- Added `POST /admin/rules/dry-run`.
- Updated the demo dashboard with a policy dry-run editor and result panel.
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `32 passed`.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `32 passed`.
- Restarted the live stack with `docker-compose up -d`.
- Smoke checks:
  - `GET /demo`: `200`
  - `GET /ready`: Redis `ok`
  - `POST /admin/rules/dry-run`: returned a valid dry-run report.

## Phase 8 Verification: 2026-05-04

- Added per-rule `algorithm` validation with `token_bucket` and `fixed_window`.
- Added Redis-backed fixed-window enforcement.
- Added `X-RateLimit-Algorithm` response header.
- Updated demo rules so `/api/data` uses `token_bucket` and `/api/limited-health` uses `fixed_window`.
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `35 passed`.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `35 passed`.
- Restarted the live stack with `docker-compose up -d`.
- Smoke checks:
  - `GET /api/data`: `X-RateLimit-Algorithm: token_bucket`
  - `GET /api/limited-health`: `X-RateLimit-Algorithm: fixed_window`
  - `GET /demo`: `200`

## Phase 9 Verification: 2026-05-04

- Added optional OpenTelemetry tracing dependencies and helper module.
- Added request spans and rate-limit decision spans.
- Added `X-Trace-ID` when tracing is enabled.
- Added tracing configuration:
  - `ENABLE_TRACING`
  - `TRACE_SERVICE_NAME`
  - `TRACE_CONSOLE_EXPORTER`
- Added agent handoff files:
  - `docs/AGENT_PROGRESS.md`
  - `docs/BACKLOG_STATUS.md`
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `36 passed`.
- Ran `docker-compose build web`.
- Result: passed.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `36 passed`.
- Restarted the live stack with `docker-compose up -d`.
- Smoke checks:
  - `GET /demo`: `200`
  - `GET /health`: `200` with `X-Request-ID`
  - `GET /ready`: Redis `ok`

## Phase 10 Verification: 2026-05-04

- Added optional SQLite telemetry persistence.
- Added `PERSIST_TELEMETRY` and `TELEMETRY_DB_PATH` configuration.
- Added `GET /admin/telemetry/persistent` for persisted event inspection.
- Kept in-memory telemetry as the fast path; SQLite writes are best-effort.
- Added runtime SQLite files to `.gitignore`.
- Added agent handoff updates:
  - `docs/AGENT_PROGRESS.md`
  - `docs/BACKLOG_STATUS.md`

- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `39 passed`.
- Ran `docker-compose build web`.
- Result: passed.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `39 passed`.
- Restarted the live stack with `docker-compose up -d`.
- Smoke checks:
  - `GET /demo`: `200`
  - `GET /ready`: Redis `ok`
  - `GET /api/data`: `200` with `X-RateLimit-Algorithm: token_bucket`
  - `GET /admin/telemetry/persistent`: persistence disabled by default with empty events.

## Phase 11 Verification: 2026-05-04

- Added README dashboard preview assets:
  - `docs/assets/demo-dashboard-desktop.png`
  - `docs/assets/demo-dashboard-mobile.png`
- Added the screenshots to the Portfolio Demo Walkthrough.
- Tightened the demo toolbar CSS so the narrow screenshot does not overflow.
- Rebuilt and restarted the Docker web service before capturing final screenshots.
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `39 passed`.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `39 passed`.
- Smoke check:
  - `GET /demo`: `200`

## Phase 12 Verification: 2026-05-04

- Added `pip-audit==2.10.0` and `bandit[toml]==1.9.4` to dev requirements.
- Added CI steps:
  - `pip-audit -r requirements.txt --cache-dir .pip-audit-cache`
  - `bandit -q -r app -c pyproject.toml`
- Added Bandit configuration in `pyproject.toml`.
- Added `make security`.
- Ignored `.pip-audit-cache/` in Git and Docker build context.
- Upgraded vulnerable dependency pins after the initial audit:
  - `fastapi`: `0.110.0` to `0.135.3`
  - `pytest`: `8.1.1` to `9.0.3`
  - `pytest-asyncio`: `0.23.6` to `1.3.0`
  - Transitive `starlette`: `0.36.3` to `1.0.0`
- Updated deprecated `HTTP_422_UNPROCESSABLE_ENTITY` constants for Starlette 1.0 compatibility.
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `39 passed`.
- Ran `.\.venv\Scripts\bandit.exe -q -r app -c pyproject.toml`.
- Result: passed.
- Ran CI-style security checks in the Linux web container.
- Result: `pip-audit` reported no known vulnerabilities and Bandit passed.
- Restarted the live stack with `docker-compose up -d`.
- Smoke checks:
  - `GET /ready`: Redis `ok`
  - `GET /api/data`: `200` with `X-RateLimit-Algorithm: token_bucket`
  - `GET /demo`: `200`
- Restarted the live stack with `docker-compose up -d`.
- Smoke checks:
  - `GET /ready`: Redis `ok`
  - `GET /api/data`: `200` with `X-RateLimit-Algorithm: token_bucket`
  - `GET /admin/rules/history`: existing initial version includes normalized `audit` metadata.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `39 passed`.

## Phase 13 Verification: 2026-05-04

- Added audit metadata to rule history entries:
  - `actor`
  - `source`
  - `reason`
  - `request_id`
  - `client_host`
- Added optional admin audit headers:
  - `X-Audit-Actor`
  - `X-Audit-Source`
  - `X-Audit-Reason`
- Captured audit metadata for rule updates, reloads, and rollbacks.
- Added a `reload` rule history event for successful disk reloads.
- Normalized legacy history entries on read so older files also return an `audit` object.
- Updated admin tests for audit metadata on update, reload, and rollback.
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `39 passed`.
- Ran `.\.venv\Scripts\bandit.exe -q -r app -c pyproject.toml`.
- Result: passed.
- Ran `docker-compose build web`.
- Result: passed.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `39 passed`.
- Ran CI-style security checks in the Linux web container.
- Result: `pip-audit` reported no known vulnerabilities and Bandit passed.

## Phase 14 Verification: 2026-05-04

- Added OTLP/HTTP trace export dependency:
  - `opentelemetry-exporter-otlp-proto-http==1.29.0`
- Added tracing configuration:
  - `TRACE_OTLP_ENABLED`
  - `TRACE_OTLP_ENDPOINT`
  - `TRACE_OTLP_HEADERS`
  - `TRACE_OTLP_TIMEOUT_S`
- Added optional `BatchSpanProcessor` plus OTLP/HTTP exporter wiring.
- Kept OTLP export disabled unless both `ENABLE_TRACING=true` and `TRACE_OTLP_ENABLED=true`.
- Added OTLP header parsing coverage.
- Ran `.\.venv\Scripts\ruff.exe check .`.
- Result: passed.
- Ran `.\.venv\Scripts\pytest.exe -q`.
- Result: `41 passed`.
- Ran `.\.venv\Scripts\bandit.exe -q -r app -c pyproject.toml`.
- Result: passed.
- Ran `docker-compose build web`.
- Result: passed.
- Ran `docker-compose run --rm --no-deps web pytest -q`.
- Result: `41 passed`.
- Ran CI-style security checks in the Linux web container.
- Result: `pip-audit` reported no known vulnerabilities and Bandit passed.

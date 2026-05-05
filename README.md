# Distributed Rate Limiter

A production-inspired distributed rate limiter built with **FastAPI** and **Redis**. The project is intentionally compact: it is small enough to read in one sitting, but complete enough to demonstrate token-bucket enforcement, atomic Redis Lua evaluation, JSON-backed rules, response headers, and passive telemetry.

This repository is being upgraded into a portfolio-ready "Rate Limiter Control Plane + Enforcement API." The current implementation focuses on the enforcement path and AI-oriented signals; the roadmap adds authenticated rule management, observability, and an interactive browser demo.

## Current Features

- **Token Bucket Engine**: Continuous token regeneration tracked in Redis.
- **Multiple Algorithms**: Rules can use `token_bucket` or `fixed_window`.
- **Atomic Redis Evaluation**: Lua scripting keeps token updates race-safe across concurrent requests.
- **JSON Rule Configuration**: Per-route global limits and identifier-specific overrides are loaded from `rules.json`.
- **Rate Limit Headers**:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`
  - `Retry-After` on HTTP `429`
- **Fail-Open Behavior**: Redis failures currently allow requests so the API remains available during limiter outages.
- **Passive Telemetry**: In-memory signals capture recent allow/deny behavior and top offenders.
- **Optional Persistent Telemetry**: `PERSIST_TELEMETRY=true` records rate-limit decisions to SQLite for restart-safe demo analytics.
- **Recommendations Endpoint**: A lightweight recommendation layer summarizes recent traffic patterns without changing rules automatically.
- **Admin Rule API**: `X-Admin-Key` protects rule inspect, validate, update, and reload endpoints.
- **Operational Endpoints**: `/health`, `/ready`, and `/metrics` expose process health, Redis readiness, and Prometheus-style counters.
- **Request Tracing**: `X-Request-ID` is accepted or generated and echoed on responses.
- **Optional OpenTelemetry Tracing**: `ENABLE_TRACING=true` emits request and limiter spans, returns `X-Trace-ID`, and can export traces to an OTLP/HTTP collector.
- **Interactive Demo Dashboard**: `/demo` provides browser controls for request simulation, live headers, signals, persisted telemetry summaries, recommendations, and active rules.

## Architecture

```text
Client
  |
  | X-API-Key or client IP
  v
FastAPI route dependency
  |
  | route path + identifier
  v
RulesManager
  |
  | rate + capacity
  v
Redis Lua token bucket
  |
  | allow / deny + remaining tokens
  v
Response headers + telemetry event
```

Core modules:

- `app/main.py`: FastAPI app, routes, and lifecycle wiring.
- `app/api/depends.py`: rate-limit dependency and response header handling.
- `app/core/limiter.py`: Redis Lua token-bucket implementation.
- `app/core/rules.py`: JSON rule loading and rule lookup.
- `app/models/rules.py`: Pydantic rule models.
- `app/ai/telemetry.py`: in-memory signals and recommendations.
- `app/observability/telemetry_store.py`: optional SQLite persistence for rate-limit events.

## Known Tradeoffs

This project is production-inspired, not fully production-ready yet. The current tradeoffs are explicit:

- **Telemetry persistence is optional**: in-memory signals stay as the fast path; SQLite persistence is best-effort and off by default.
- **JSON-backed rules**: easy to inspect and backed by local version history, but still not a multi-user database or approval workflow.
- **Demo admin key**: admin and AI endpoints are protected by `X-Admin-Key`, with a development default that should be overridden outside local demos.
- **Fail-open by default**: good for availability demos, risky for sensitive endpoints; sensitive demo routes can opt into fail-closed.
- **Identifier hashing defaults off**: API keys and IPs can be hashed in Redis keys and telemetry with `HASH_IDENTIFIERS=true`, but the default keeps demo behavior easy to inspect.

These are intentionally tracked in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) and [docs/EXECUTION_STRATEGY.md](docs/EXECUTION_STRATEGY.md).

## Tech Stack

- **Backend**: Python 3.11+, FastAPI
- **Limiter State**: Redis 7
- **Atomicity**: Redis Lua scripting
- **Validation**: Pydantic
- **Testing**: Pytest, pytest-asyncio, fakeredis
- **Security Checks**: pip-audit dependency audit and Bandit static scan
- **Demo UI**: Static HTML/CSS/JavaScript served by FastAPI
- **Deployment**: Docker and Docker Compose

## Running With Docker

Docker Compose starts two services:

- `web`: FastAPI app at `http://localhost:8001`
- `redis`: Redis at `localhost:6378`

```bash
docker compose up --build
```

Run tests inside the app container:

```bash
docker compose exec web pytest -q
```

Stop the stack:

```bash
docker compose down
```

## Running Locally

Docker is the recommended path for reviewers because it includes Redis. For local Python development, create a fresh virtual environment with Python 3.11 or newer:

```powershell
uv venv .venv --python 3.11
uv pip install --python .\.venv\Scripts\python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

In another terminal, make sure Redis is available at `redis://localhost:6379/0`, then run:

```powershell
.\.venv\Scripts\pytest.exe -q
```

If an old virtual environment points to a missing Python installation, recreate it before running tests.

## Developer Commands

```bash
make test
make lint
make security
make compose-up
make load-test
```

Without `make`, the equivalent checks are:

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\bandit.exe -q -r app -c pyproject.toml
docker compose up --build
.\.venv\Scripts\python.exe scripts\load_test.py --base-url http://localhost:8001
```

## Configuration

Rules live in [rules.json](rules.json).

```json
{
  "routes": {
    "/api/data": {
      "global_limit": {
        "rate": 1.0,
        "capacity": 5
      },
      "overrides": {
        "premium_user_key": {
          "rate": 10.0,
          "capacity": 100
        }
      }
    }
  }
}
```

Behavior today:

- `X-API-Key` is used as the rate-limit identifier when present.
- Client IP is used when `X-API-Key` is missing.
- Identifier-specific overrides win over the route's global limit.
- Missing routes fall back to a default rule.
- `/health` is not rate-limited.
- `/api/data` uses `token_bucket` by default.
- `/api/limited-health` uses `fixed_window` for demo traffic.
- `PERSIST_TELEMETRY=true` enables SQLite event persistence.
- `TELEMETRY_DB_PATH=data/telemetry.sqlite3` controls the SQLite database path.

## Operations

- `GET /health`: process health, not rate-limited.
- `GET /ready`: Redis readiness.
- `GET /metrics`: Prometheus-style in-memory counters.
- `X-Request-ID`: accepted when provided, generated when missing, and echoed on every response.
- `X-Trace-ID`: emitted when OpenTelemetry tracing is enabled.
- `TRACE_OTLP_ENABLED=true`: exports spans to an OTLP/HTTP collector when tracing is enabled.
- `TRACE_OTLP_ENDPOINT`: optional trace endpoint such as `http://localhost:4318/v1/traces`.
- `TRACE_OTLP_HEADERS`: optional comma-separated OTLP headers, such as `authorization=Bearer token,x-tenant=demo`.

## Admin API

Admin endpoints use the `X-Admin-Key` header. The development default is `dev-admin-key`.

```bash
curl http://localhost:8001/admin/rules -H "X-Admin-Key: dev-admin-key"
```

Rule-changing endpoints can include optional audit headers:

- `X-Audit-Actor`: human or automation actor.
- `X-Audit-Source`: dashboard, runbook, CLI, or integration source.
- `X-Audit-Reason`: short reason for the change.

Available endpoints:

- `GET /admin/rules`
- `GET /admin/telemetry/persistent`
- `GET /admin/rules/history`
- `POST /admin/rules/validate`
- `POST /admin/rules/dry-run`
- `PUT /admin/rules`
- `POST /admin/rules/rollback/{version}`
- `POST /admin/rules/reload`

## Portfolio Demo Walkthrough

Start the stack:

```bash
docker compose up --build
```

Open the dashboard:

```text
http://localhost:8001/demo
```

Dashboard preview:

![Rate limiter demo dashboard desktop preview](docs/assets/demo-dashboard-desktop.png)

Narrow layout preview:

![Rate limiter demo dashboard narrow preview](docs/assets/demo-dashboard-mobile.png)

Use the dashboard to send single requests, send a burst, compare free and premium clients, inspect rate-limit headers, load admin-only signals/persisted telemetry/rules/history, and dry-run proposed policy changes with `X-Admin-Key`.

Trigger the global `/api/data` limit:

```powershell
for ($i = 1; $i -le 7; $i++) {
  curl.exe -i http://localhost:8001/api/data -H "X-API-Key: free_user_key"
}
```

Compare a premium client override:

```powershell
for ($i = 1; $i -le 7; $i++) {
  curl.exe -i http://localhost:8001/api/data -H "X-API-Key: premium_user_key"
}
```

View passive telemetry:

```bash
curl http://localhost:8001/ai/signals -H "X-Admin-Key: dev-admin-key"
```

View persisted telemetry when `PERSIST_TELEMETRY=true`:

```bash
curl http://localhost:8001/admin/telemetry/persistent -H "X-Admin-Key: dev-admin-key"
```

Generate recommendations:

```bash
curl -X POST http://localhost:8001/ai/recommendations -H "X-Admin-Key: dev-admin-key"
```

What to look for:

- `200` responses while tokens remain.
- `429` responses after a bucket is exhausted.
- `X-RateLimit-Remaining` decreasing across requests.
- `X-RateLimit-Algorithm` showing the active limiter strategy.
- `Retry-After` on denied requests.
- Top offenders and route-level `429` ratios in `/ai/signals`.

## Upgrade Status

Completed in this upgrade pass:

- Phase 0: README positioning, architecture notes, known tradeoffs, and demo walkthrough.
- Phase 1: accurate `Retry-After`, fractional token preservation, rule validation, and route-level fail-open/fail-closed behavior.
- Phase 2: authenticated admin APIs for rule inspect, validate, update, and reload, plus admin protection for AI endpoints.
- Phase 3: metrics, readiness checks, request IDs, structured logs, split health routes, and optional identifier hashing.
- Phase 4: lightweight static `/demo` dashboard for request simulation, headers, telemetry, recommendations, and rules.
- Phase 5: CI workflow, ruff linting, `.env.example`, Makefile commands, and load-test script.
- Phase 6: rule version history and rollback endpoints for safer control-plane demos.
- Phase 7: policy dry-run endpoint and dashboard panel for estimating proposed rule impact.
- Phase 8: per-rule limiter algorithms with token-bucket and fixed-window strategies.
- Phase 9: optional OpenTelemetry tracing for request and rate-limit decision spans.
- Phase 10: optional SQLite telemetry persistence and admin inspection endpoint.
- Phase 11: README dashboard preview assets for desktop and narrow layouts.
- Phase 12: CI dependency audit and static security scanning, plus security-driven dependency upgrades.
- Phase 13: richer rule history audit metadata for updates, reloads, and rollbacks.
- Phase 14: optional OpenTelemetry OTLP/HTTP exporter configuration.
- Phase 15: persisted telemetry summaries in the demo dashboard.

See [docs/PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md), [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md), and [docs/EXECUTION_STRATEGY.md](docs/EXECUTION_STRATEGY.md) for the full product and execution plan.

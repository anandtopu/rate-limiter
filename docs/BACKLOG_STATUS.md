# Backlog Status

## Done

- Correct `Retry-After`.
- Validate positive rule values.
- Add admin API key protection for AI/admin endpoints.
- Add rule validation endpoint.
- Update README positioning.
- Add rule update/reload APIs.
- Add demo dashboard.
- Add metrics endpoint.
- Add request ID middleware and structured logs.
- Split platform health from rate-limited demo health.
- Add route-level fail-open/fail-closed.
- Hash identifiers in Redis keys and telemetry.
- Add CI workflow and linting.
- Add `.env.example`.
- Add load-test script.
- Add rule version history.
- Add policy dry-run mode.
- Add multiple limiter algorithms.
- Add OpenTelemetry tracing.
- Persist telemetry in SQLite.
- Add dashboard screenshots to README.
- Add dependency and security scanning in CI.
- Add richer rule audit metadata such as actor, source, and reason.
- Add optional OpenTelemetry OTLP exporter configuration.
- Add richer persisted telemetry summaries in the dashboard.
- Add generated SBOM artifact in CI.
- Add UI controls for rule update audit metadata.
- Add a local collector compose profile for tracing demos.
- Add persistent telemetry time-range filters.
- Add Docker Compose health checks for Redis and the web app.
- Add trusted reverse-proxy policy for `X-Forwarded-For` client identity.
- Add templated route keys for path-parameter routes.
- Add route owner and sensitivity metadata to rules, observability, and demo configuration.
- Add a sensitive-rule approval workflow with pending changes and second-admin approval.
- Add an optional SQLite-backed durable rule store while preserving the JSON default path.
- Add dashboard support for pending rule approvals with approve/reject controls and audit metadata.
- Add a dedicated rule-change audit API and dashboard view with route, actor, action, sensitivity, and time-range filters.
- Add a Redis outage demo script for fail-open and fail-closed behavior.
- Add recommendation-to-dry-run support for editable proposed policy JSON from AI suggestions.
- Add benchmark output from `scripts/load_test.py` to documentation for free, premium, abusive, and templated-route scenarios.

## Remaining

### P0: Next Implementation Candidates

- No P0 implementation candidates remain from the current queue.

### P1: Product And Demo Polish

- Add coverage reporting in CI so test depth is visible alongside lint, security scan, and SBOM checks.

### P2: Advanced Platform Enhancements

- Add a sliding-window algorithm behind the existing per-rule algorithm selection.
- Add admin key rotation support or multiple named admin keys for local/demo environments.
- Add rule import/export helpers for sharing demo policies and restoring known-good demo states.
- Add OpenAPI examples for admin rule management, dry runs, rollback, persistent telemetry filters, and metadata fields.

## Resume Notes

- The original portfolio upgrade backlog is complete through Phase 30. The remaining items above are the next implementation queue, not unfinished work from the original MVP pass.
- `scripts/load_test.py` now covers free, premium, abusive fixed-window, and templated account-data scenarios. README includes representative benchmark output.
- `POST /admin/rules/recommendation-draft` converts current AI recommendations into editable rule JSON and returns a dry-run report without applying changes.
- `scripts/redis_outage_demo.py` stops the Compose Redis service, probes the fail-open and fail-closed demo routes, and restores Redis. Use `--skip-stop` for probe-only mode.
- Rule history now has a filtered audit view at `GET /admin/rules/audit`, and the dashboard exposes route, actor, action, sensitivity, range, and limit filters.
- The dashboard now has a Pending Approvals panel that lists sensitive-rule proposals, exposes proposer audit metadata, and can approve or reject with the current audit headers.
- `RULE_STORE_BACKEND=sqlite` enables a durable local rule store at `RULE_STORE_DB_PATH`; it seeds from `RULES_PATH` on first run and then persists active rules, history, and pending approvals in SQLite.
- Sensitive rule updates now return a pending approval instead of applying immediately. `GET /admin/rules/pending` lists requests, and `/approve` requires a different `X-Audit-Actor` before applying to the active rule store and history.
- Docker Compose now checks Redis with `redis-cli ping`, waits for Redis before starting `web`, and checks the app through `/ready`.
- Anonymous client IP resolution now ignores `X-Forwarded-For` unless the direct peer is included in `TRUSTED_PROXY_IPS`.
- Rate-limit rules and telemetry now use FastAPI route templates, such as `/api/accounts/{account_id}/data`, when a route has path parameters.
- Rule metadata now includes optional `owner` and validated `sensitivity` labels, alongside existing tier metadata, and those labels flow into decision logs and limiter spans.
- Persisted telemetry now supports `since`, `until`, and `limit` query parameters. The dashboard has range and event-count controls for the persisted telemetry panel.
- Docker Compose now has a `tracing` profile with an OpenTelemetry collector. Run it with `ENABLE_TRACING=true`, `TRACE_OTLP_ENABLED=true`, and `TRACE_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces`.
- The demo dashboard now has Rule Change Controls for audited rule updates, reloads, and rollbacks. Mutations send `X-Audit-Actor`, `X-Audit-Source`, and `X-Audit-Reason` from the UI.
- CI now generates and uploads a reproducible CycloneDX JSON SBOM as the `cyclonedx-sbom` artifact. Local developers can run `make sbom`.
- The dashboard now has a Persisted Telemetry panel backed by `/admin/telemetry/persistent`, with counters, route summaries, top offenders, and recent persisted events. It reports disabled cleanly when persistence is off.
- OTLP/HTTP trace export is controlled by `TRACE_OTLP_ENABLED`, `TRACE_OTLP_ENDPOINT`, `TRACE_OTLP_HEADERS`, and `TRACE_OTLP_TIMEOUT_S`; it only initializes when `ENABLE_TRACING=true`.
- Rule history now records audit metadata for updates, reloads, and rollbacks. Admin callers can pass `X-Audit-Actor`, `X-Audit-Source`, and `X-Audit-Reason`; request ID and client host are captured automatically.
- CI now runs `pip-audit` for dependency CVEs and Bandit for static security scanning.
- `pip-audit` initially flagged vulnerable `pytest` and transitive `starlette`; requirements now use `pytest==9.0.3`, `pytest-asyncio==1.3.0`, and `fastapi==0.135.3`, which resolves to `starlette==1.0.0`.
- README now includes desktop and narrow dashboard screenshots from `docs/assets/`.
- Telemetry persistence is implemented with SQLite, disabled by default, and controlled by `PERSIST_TELEMETRY` plus `TELEMETRY_DB_PATH`.
- In-memory telemetry remains the fast path; SQLite writes are best-effort so request handling keeps working if persistence fails.

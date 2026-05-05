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

## Remaining

- Add a local collector compose profile for tracing demos.
- Add persistent telemetry time-range filters.

## Resume Notes

- The next technical backlog item is a local collector compose profile for tracing demos.
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

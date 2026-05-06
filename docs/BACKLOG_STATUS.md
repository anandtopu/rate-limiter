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
- Add coverage reporting in CI with terminal summary and uploaded XML artifact.
- Add a sliding-window algorithm behind the existing per-rule algorithm selection.
- Add multiple named admin keys for local rotation demos and audit attribution.
- Add rule import/export helpers for sharing demo policies and restoring known-good demo states.
- Add OpenAPI examples for admin rule management, dry runs, rollback, persistent telemetry filters, and metadata fields.
- Complete AI-P0 telemetry feature foundation with enriched decision events, SQLite telemetry migration, and deterministic feature extraction.
- Complete AI-P1 advisor v2 with structured tuning, abuse, reliability, and algorithm recommendations.
- Complete AI-P2 replay-based counterfactual dry-run with route and identifier impact summaries.
- Complete AI-P3 anomaly and abuse detection with route spikes, retry loops, concentrated offenders, sensitive-route probing, Redis outage exposure, admin API visibility, and dashboard output.
- Complete AI-P4 optional policy copilot with disabled-by-default configuration, provider adapter boundary, fake local adapter, admin endpoint, validation, replay dry-run, and dashboard controls.
- Complete AI-P5 research evaluation harness with labeled scenarios, recommendation/anomaly precision and recall, false-positive notes, denied-legitimate estimates, abuse-reduction estimates, and policy-stability reporting.
- Harden advisor tuning so concentrated abusive route-identifier pressure suppresses broad route-limit tuning recommendations.
- Add an OpenAI-compatible HTTP provider adapter behind the AI-P4 policy copilot boundary while preserving the deterministic fake adapter for local tests.
- Add live HTTP AI evaluation that compares Redis-backed response captures with the deterministic synthetic baseline.
- Add persisted SQLite telemetry replay windows to the AI evaluation harness.
- Add optional Redis-outage mode to live AI evaluation for end-to-end reliability-scenario coverage.
- Add a generated AI research report artifact that combines synthetic, live, outage, and persisted evaluation summaries.
- Add CI-friendly AI dry-run artifacts that do not require Docker, Redis, or a live app.
- Add an admin API endpoint and dashboard panel for the latest generated AI research report artifact.
- Add CI workflow wiring that uploads the AI dry-run artifact bundle.
- Add raw Markdown and attachment download support for the AI research report admin endpoint.
- Add manifest files inside the AI CI dry-run artifact bundle for reviewer navigation.
- Add a dashboard download control for the AI research report Markdown artifact.
- Add CI artifact reviewer guidance for coverage, SBOM, and AI dry-run bundles.
- Add dashboard report download filename and byte-count status feedback.
- Add server-provided report download filename handling in the dashboard.
- Add a canonical report `download_url` to admin JSON metadata and dashboard output.
- Add `scripts/ai_ci_dry_run.py --list-scenarios` for persisted fixture discovery.
- Add AI CI manifest coverage for reviewer entrypoints, section counts, and artifact statuses.
- Add an optional dashboard screenshot refresh helper for the AI Research Report panel.
- Add explicit 30-day CI artifact retention for coverage, SBOM, and AI dry-run uploads.

## Remaining

### P0: Next Implementation Candidates

- No P0 implementation candidates remain from the AI research queue.

### P1: Product And Demo Polish

- P1 AI research queue is complete.

### P2: Advanced Platform Enhancements

- P2 AI research queue is complete.

## Resume Notes

- The original portfolio upgrade backlog is complete through Phase 35. The new queue is the AI research upgrade described in [AI_RESEARCH_ROADMAP.md](AI_RESEARCH_ROADMAP.md).
- The AI research queue is complete through AI-P5. Next work should be selected from new user priorities or follow-up hardening identified by the evaluation report.
- The twenty-third and twenty-fourth post-AI-P5 hardening passes add optional dashboard screenshot refresh automation for the AI Research Report panel and explicit 30-day retention for CI review artifacts.
- The thirteenth through twenty-second post-AI-P5 hardening passes improve reviewer ergonomics for CI artifacts and report downloads: README artifact guidance, dashboard filename/byte-count feedback, server-provided download filenames, report `download_url` metadata, scenario discovery via `scripts/ai_ci_dry_run.py --list-scenarios`, stronger manifest tests, and refreshed verification.
- The twelfth post-AI-P5 hardening pass adds a dashboard Download action to the AI Research Report panel. It fetches `/admin/ai/research-report?format=markdown&download=true` with the current `X-Admin-Key` and saves `AI_RESEARCH_REPORT.md` from the browser.
- The eleventh post-AI-P5 hardening pass adds `MANIFEST.md` and `manifest.json` to `scripts/ai_ci_dry_run.py` output, summarizing artifact paths, byte counts, statuses, entrypoints, and limitations for CI artifact reviewers.
- The tenth post-AI-P5 hardening pass extends `GET /admin/ai/research-report` with `format=json|markdown` and `download=true`, preserving the JSON dashboard view while enabling raw `text/markdown` responses and attachment downloads.
- The ninth post-AI-P5 hardening pass updates GitHub Actions to run `python scripts/ai_ci_dry_run.py --output-dir tmp-test-data/ai-ci-dry-run` and upload that directory as the `ai-ci-dry-run` artifact.
- The eighth post-AI-P5 hardening pass adds `GET /admin/ai/research-report`, `AI_RESEARCH_REPORT_PATH`, OpenAPI coverage, and a dashboard AI Research Report panel for reading the generated Markdown artifact through the protected admin control plane.
- The seventh post-AI-P5 hardening pass adds `scripts/ai_ci_dry_run.py` and `make ai-ci-dry-run`. It writes deterministic synthetic evaluation JSON, a seeded local SQLite telemetry fixture, persisted replay JSON, and combined research-report artifacts under `tmp-test-data/ai-ci-dry-run` without starting Docker, Redis, or the app.
- The sixth post-AI-P5 hardening pass adds `scripts/ai_research_report.py`, `make ai-research-report`, and [AI_RESEARCH_REPORT.md](AI_RESEARCH_REPORT.md). The report includes the deterministic synthetic baseline by default and can fold in saved live, outage, and persisted evaluation JSON.
- The fifth post-AI-P5 hardening pass adds `scripts/ai_live_eval.py --include-redis-outage`, which can stop Compose Redis, capture sensitive-route fail-open traffic, restore Redis, and compare the live reliability labels with the synthetic `redis-outage-exposure` scenario.
- The fourth post-AI-P5 hardening pass extends `scripts/ai_eval.py` with `--telemetry-db`, `--since`, `--until`, `--limit`, `--window-name`, and optional `--expected-scenario` for replaying persisted SQLite telemetry windows.
- The third post-AI-P5 hardening pass adds `scripts/ai_live_eval.py` and `make ai-live-eval`. The script sends live HTTP traffic, rebuilds AI evaluation events from response headers and status codes, and compares observed labels with `scripts/ai_eval.py`.
- The second post-AI-P5 hardening pass adds `AI_COPILOT_PROVIDER=openai_compatible` with `AI_COPILOT_ENDPOINT`, optional `AI_COPILOT_API_KEY`, `AI_COPILOT_MODEL`, and `AI_COPILOT_TIMEOUT_S`. Provider failures return `502`, while disabled or missing provider configuration still returns `503`.
- The first post-AI-P5 hardening pass suppresses route-wide tuning when route denials are dominated by a single abusive identifier. `scripts/ai_eval.py` now reports 9 stable scenarios with recommendation precision `1.0`, recommendation recall `1.0`, anomaly precision `1.0`, and anomaly recall `1.0`.
- AI-P5 added `scripts/ai_eval.py`, `make ai-eval`, and tests for labeled research scenarios covering normal free traffic, premium bursts, abusive identifiers, retry loops, route spikes, sensitive-route probing, Redis outage exposure, fixed-window pressure, and mixed workloads.
- AI-P4 added `app/ai/copilot.py`, `POST /admin/ai/policy-copilot`, disabled-by-default `AI_COPILOT_ENABLED`, fake provider support, safe validation/dry-run of generated rule JSON, and a dashboard Policy Copilot panel. The endpoint returns `applied: false` and never mutates active rules.
- AI-P3 added `app/ai/anomalies.py`, includes anomaly summaries in `/ai/signals`, exposes `GET /admin/ai/anomalies`, and adds a dashboard Anomalies panel. Findings include stable IDs, type, severity, route or identifier scope, rationale, evidence, and suggested next actions.
- AI-P2 added `app/ai/simulation.py` and extends dry-run reports with a `replay` section covering events replayed, observed/current/proposed denials, newly denied, newly allowed, route impact, identifier impact, and sensitive-route impact.
- AI-P1 added deterministic advisor engines in `app/ai/advisors.py` for tuning, abuse, reliability, and algorithm recommendations. `/ai/recommendations` now returns schema version 2 recommendations with stable IDs, confidence, rationale, proposed changes, expected impact, and safety notes while preserving legacy recommendation fields.
- AI-P0 added enriched telemetry fields for algorithm, fail mode, tier, owner, sensitivity, rule version, method, status code, and optional latency; SQLite telemetry stores migrate old schemas forward; `app/ai/features.py` summarizes route, identifier, and route-identifier pressure.
- OpenAPI now includes examples for admin rule metadata, dry-run payloads and responses, import envelopes, rollback responses, and persistent telemetry filters.
- Rule policies can now be exported with `GET /admin/rules/export` and restored with `POST /admin/rules/import`; imports validate before applying, record `import` history entries, and queue sensitive-route changes for approval.
- `ADMIN_API_KEYS` accepts comma-separated named keys such as `primary:key-one,backup:key-two`; named keys work alongside `ADMIN_API_KEY`, provide default audit actors, and can be verified by name through `GET /admin/keys` without exposing secrets.
- Rules can now select `sliding_window`; the templated account-data demo route uses it.
- CI now runs pytest with coverage for `app` and `scripts`, prints a missing-line summary, and uploads `coverage.xml` as the `coverage-xml` artifact. Local developers can run `make coverage`.
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

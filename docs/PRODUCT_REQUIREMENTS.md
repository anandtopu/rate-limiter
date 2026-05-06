# Product Requirements Document: Portfolio Rate Limiter

## 1. Overview

This project is currently a compact FastAPI + Redis token-bucket rate limiter with JSON-based rules, rate-limit response headers, fail-open behavior, and in-memory AI-oriented telemetry. It is a strong starter application for learning distributed rate limiting, but it needs clearer product boundaries, safer operations, better demo ergonomics, and more realistic observability to work well as a portfolio showcase.

The target product is a demo-ready "Rate Limiter Control Plane + Enforcement API" that shows backend system design, distributed consistency, operational safety, and a small AI-assisted observability layer.

The next research track evolves that observability layer into an AI-assisted advisor for rate-limit policy analysis. The advisor should explain traffic patterns, detect suspicious behavior, draft safer policies, and evaluate expected impact without making autonomous enforcement decisions.

## 2. Product Goals

- Demonstrate a production-inspired distributed rate limiter using Redis Lua for atomic token bucket evaluation.
- Provide a visible, interactive demo experience so reviewers can understand behavior without reading source code first.
- Support safe rule inspection and updates through authenticated admin APIs.
- Expose operational signals: request outcomes, top offenders, fail-open events, and actionable recommendations.
- Make reliability tradeoffs explicit, especially fail-open vs fail-closed behavior.
- Ship with tests, Docker setup, and documentation that make the project easy to run and evaluate.
- Research AI-assisted policy tuning while keeping the request enforcement path deterministic.
- Provide explainable recommendations with evidence, confidence, expected impact, and safety constraints.

## 3. Non-Goals

- Full multi-tenant SaaS billing, user management, or organization hierarchy.
- A distributed telemetry store for long-term analytics.
- Advanced ML model integration or automated rule changes.
- AI/model calls in the request enforcement path.
- Fully autonomous rate-limit policy mutation.
- A complete WAF or abuse-prevention platform.
- Production secrets management beyond demo-safe configuration patterns.

## 4. Target Users

- Portfolio reviewers and hiring teams evaluating backend architecture skill.
- Developers learning rate limiting, Redis atomic operations, and FastAPI middleware/dependencies.
- API platform teams wanting a small reference implementation for edge rate limiting concepts.
- Researchers or platform engineers evaluating safe AI-assisted traffic policy workflows.

## 5. Current Capabilities

- FastAPI routes protected by a `rate_limit` dependency.
- Redis Lua token-bucket implementation with atomic evaluation.
- Per-route rules loaded from `rules.json`.
- Identifier selection by `X-API-Key`, falling back to client IP.
- Standard-ish response headers:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`
  - `Retry-After` on `429`
- In-memory telemetry endpoint at `GET /ai/signals`.
- Recommendation endpoint at `POST /ai/recommendations`.
- Authenticated admin rule inspection, validation, update, reload, history, and rollback APIs.
- Unit and API tests using `fakeredis`.
- Docker Compose with API and Redis services.

## 6. Key Gaps To Fix

### Product and Demo Gaps

- No interactive demo UI; reviewers must use curl or read tests.
- No explicit scenarios such as free vs premium API keys, abusive client, Redis outage, or rule tuning.
- README describes the project as production-ready, while several operational safeguards are still starter-level.
- AI/recommendation endpoints are useful, but their purpose and limits should be clearer in the product flow.

### API and Control Plane Gaps

- No admin API to inspect, validate, reload, or update rules.
- No authentication on internal/admin-like endpoints, including AI telemetry.
- Rules are file-backed with local version history, rollback, and lightweight audit metadata, but no multi-user approval workflow.
- Exact route-path matching will not handle templated routes well if the API grows. (Implemented in Phase 22 with FastAPI route templates.)
- Endpoint-level metadata for route owner, tier, sensitivity, and fail behavior is now available in rules and observability, but there is still no approval workflow around sensitive policy changes.

### Rate Limiting Correctness Gaps

- `Retry-After` currently uses time-to-full-bucket rather than time until the next token is available. For a denied request with capacity 5 and rate 1 token/sec, the API may return about 5 seconds when the next request can succeed after about 1 second.
- Remaining tokens are returned as an integer, which hides fractional refill state and can make headers look less precise.
- Rule values do not enforce positive `rate` and `capacity` constraints.
- Redis keys include raw route and identifier values; this is clear for learning, but privacy and key-length considerations should be addressed.
- Fail-open is hard-coded. Sensitive routes should be able to choose fail-open or fail-closed.

### Observability and Operations Gaps

- Telemetry is in-memory only and process-local, so signals reset on restart and diverge across workers.
- No Prometheus-style metrics endpoint.
- Redis failures are printed instead of structured logs.
- No Docker health checks or Redis readiness endpoint.
- Baseline had no CI workflow, linting, coverage gate, or dependency/security checks; the upgrade pass now includes CI, linting, tests, `pip-audit`, Bandit, and CycloneDX SBOM generation.

### Security Gaps

- Admin and AI endpoints have no API key, role, or network boundary.
- API keys are used directly as Redis key material and telemetry identifiers.
- No clear trust policy for `X-Forwarded-For` or reverse proxy headers. (Implemented in Phase 21 with `TRUSTED_PROXY_IPS`.)
- No request ID or correlation ID for tracing rate-limit decisions.

## 7. Proposed Product Scope

### MVP Portfolio Upgrade

The MVP should make the project feel complete without turning it into a large platform.

- Add authenticated admin APIs:
  - `GET /admin/rules`
  - `POST /admin/rules/validate`
  - `PUT /admin/rules`
  - `POST /admin/rules/reload`
- Add a demo dashboard served by FastAPI:
  - Request simulator for `/health` and `/api/data`
  - API key selector: anonymous, free user, premium user, abusive client
  - Live response headers and status history
  - Telemetry and recommendations panel
  - Rule viewer/editor for demo mode
- Improve limiter correctness:
  - Accurate `Retry-After`
  - Positive rule validation
  - Optional route-level fail mode: `open` or `closed`
  - Safer identifier hashing for Redis keys and telemetry display controls
- Add observability:
  - Structured logs for allow, deny, and fail-open decisions
  - `GET /metrics` for counters and gauges
  - Redis readiness included in health diagnostics
- Strengthen docs:
  - Honest README positioning
  - Architecture diagram
  - Demo script
  - Tradeoff notes

### Follow-Up Enhancements

- Persist rules in Redis or SQLite with versions and audit history.
- Add sliding-window or fixed-window algorithms behind a strategy interface.
- Add policy dry-run mode to compare proposed rules against observed traffic.
- Add load-test scripts and benchmark results.
- Add OpenTelemetry tracing and optional OTLP exporter configuration.
- Add GitHub Actions CI. (Implemented with lint, tests, dependency audit, static security scan, and SBOM artifact upload.)

### AI Research Upgrade

The AI research upgrade should be implemented as a control-plane advisor. It consumes telemetry and active rules, then produces recommendations and policy drafts that pass through validation, dry-run, audit, approval, and rollback workflows.

Primary capabilities:

- Enriched telemetry and feature extraction for route, identifier, and route-identifier behavior.
- Structured advisor recommendations for tuning, abuse, reliability, and algorithm selection.
- Replay-based counterfactual dry-runs against recent or persisted traffic.
- Anomaly detection for traffic spikes, retry loops, concentrated offenders, sensitive-route probing, and Redis outage exposure.
- Optional LLM policy copilot for explanations and validated draft rules.
- Repeatable evaluation scenarios and research reports with precision/recall, false-positive notes, denied-legitimate estimates, abuse-reduction estimates, and stated limitations.

The detailed backlog is maintained in [AI_RESEARCH_ROADMAP.md](AI_RESEARCH_ROADMAP.md).

## 8. Functional Requirements

### Enforcement

- The API must allow requests when the selected bucket has enough tokens.
- The API must reject requests with HTTP `429` when a bucket is exhausted.
- The API must include rate-limit headers on allowed and denied responses.
- The API must calculate `Retry-After` as the time until enough tokens exist for the rejected request.
- The API must support per-route global limits and identifier overrides.
- The API must support configurable fail behavior per route.

### Rule Management

- Admin users must be able to retrieve the active rule set.
- Admin users must be able to validate a proposed rule set without applying it.
- Admin users must be able to update rules when validation passes.
- Admin users must be able to reload rules from the configured backing store.
- Rule updates must reject invalid rates, capacities, unknown fail modes, and malformed route definitions.

### Demo Dashboard

- Users must be able to trigger requests from the browser.
- Users must see status code, response body, and rate-limit headers.
- Users must see recent allow/deny history.
- Users must see AI signals and generated recommendations.
- Demo controls must work with default Docker Compose setup.

### Observability

- The app must record allow, deny, and Redis failure events.
- The app must expose aggregate metrics suitable for dashboards.
- The app must surface Redis connectivity status.
- The app must include request IDs in logs and responses.

### AI Advisor

- The app should extract feature summaries from recent and persisted telemetry.
- The app should generate explainable recommendations with evidence and confidence.
- The app should distinguish under-provisioned routes from likely abusive identifiers where possible.
- The app should estimate the impact of proposed policies before application.
- The app should never let AI output mutate active rules without validation and admin action.
- The app should support offline tests with deterministic advisors and fake LLM adapters.

### Security

- Admin and internal telemetry endpoints must require an admin API key in demo mode.
- Public protected API routes must continue to use `X-API-Key` as the rate-limit identity.
- Identifiers used in Redis keys should be hashed or normalized.
- Documentation must describe how proxy IP extraction should be configured safely. (Implemented in Phase 21.)

## 9. Non-Functional Requirements

- Local setup must work with `docker compose up --build`.
- Tests must run without a real Redis dependency using `fakeredis`.
- The limiter path should remain low-latency and avoid unnecessary external calls.
- Core enforcement must be concurrency-safe under simultaneous requests.
- The code should remain beginner-readable, with clear module boundaries.
- Demo UI should be lightweight and avoid adding a large frontend toolchain unless needed.
- AI analysis must run outside the hot request path.
- Optional LLM features must be disabled by default and must not be required for local tests.

## 10. Success Metrics

- A reviewer can run the project and understand the rate limiter behavior within 5 minutes.
- Tests cover limiter correctness, API headers, admin rule validation, telemetry, and fail behavior.
- Demo dashboard shows allowed and denied requests without needing curl.
- README accurately explains architecture, limitations, and tradeoffs.
- `Retry-After` and rule validation behavior are correct and documented.
- AI recommendations are evaluated against repeatable scenarios with documented limitations.

## 11. Acceptance Criteria

- `docker compose up --build` starts API, Redis, and the demo dashboard.
- `GET /demo` loads an interactive dashboard.
- Protected routes return accurate rate-limit headers.
- Exhausted buckets return `429` with accurate `Retry-After`.
- Admin endpoints reject missing or invalid admin API keys.
- Invalid rules cannot be applied.
- Metrics and AI signals reflect request activity.
- Test suite passes locally.

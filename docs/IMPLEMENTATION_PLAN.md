# Implementation Plan: Portfolio Rate Limiter Upgrade

## 1. Guiding Approach

Keep the project small enough to be readable, but complete enough to tell a strong portfolio story. The first pass should prioritize correctness, demo experience, and operational credibility over large platform features.

Recommended implementation order:

1. Fix correctness and validation issues in the existing backend.
2. Add admin/security boundaries.
3. Add demo UI and observability.
4. Polish documentation, tests, and developer workflow.

## 2. Phase 0: Baseline and Documentation Cleanup

### Objectives

- Align README language with the current maturity of the app.
- Add a short architecture diagram and demo script.
- Establish the product roadmap in docs.

### Tasks

- Update `README.md` to position the project as "production-inspired" rather than fully production-ready.
- Add a "Known Tradeoffs" section:
  - In-memory telemetry
  - JSON-backed rules
  - Demo admin key
  - Fail-open behavior
- Add a "Portfolio Demo Walkthrough" section:
  - Start Docker Compose
  - Hit `/demo`
  - Simulate free and premium clients
  - Trigger `429`
  - View signals and recommendations

### Tests/Checks

- Manual README command review.
- Confirm Docker commands match actual service names.

## 3. Phase 1: Limiter Correctness and Rule Validation

### Objectives

- Make the core rate-limiting behavior defensible in a technical review.
- Prevent invalid rules from causing runtime bugs.

### Proposed File Changes

- `app/models/rules.py`
  - Add validation constraints:
    - `rate > 0`
    - `capacity > 0`
  - Add optional fields:
    - `fail_mode: Literal["open", "closed"] = "open"`
    - `description: str | None`
    - `tier: str | None`
- `app/core/limiter.py`
  - Return more detailed limiter result data:
    - `allowed`
    - `remaining`
    - `retry_after_s`
    - `reset_timestamp`
    - `redis_fail_open`
  - Preserve fractional token math internally.
  - Calculate `retry_after_s` from missing tokens, not time-to-full.
- `app/api/depends.py`
  - Use the new result object.
  - Apply route-level fail mode.
  - Normalize header calculation in one helper.
- `rules.json`
  - Add metadata and fail mode examples.

### Acceptance Criteria

- Denied requests return `Retry-After` equal to the time until the next allowed request.
- Invalid `rate` or `capacity` values fail validation.
- Existing tests continue to pass after expected assertions are updated.

### Tests

- Add tests for:
  - Invalid rules fail Pydantic validation.
  - `Retry-After` for capacity 5, rate 1 is about 1 second after a single-token request denial.
  - Fail-closed route rejects when Redis is unavailable.
  - Fail-open route allows when Redis is unavailable.

## 4. Phase 2: Admin API and Security Boundary

### Objectives

- Add a small control plane for inspecting and managing rules.
- Protect internal endpoints in a demo-appropriate way.

### Proposed File Changes

- `app/config.py`
  - Add settings:
    - `admin_api_key`
    - `rules_path`
    - `expose_demo_dashboard`
    - `hash_identifiers`
- `app/api/admin.py`
  - New router for admin endpoints:
    - `GET /admin/rules`
    - `POST /admin/rules/validate`
    - `PUT /admin/rules`
    - `POST /admin/rules/reload`
- `app/api/security.py`
  - Admin API key dependency.
- `app/core/rules.py`
  - Add `validate_rules(data)` method.
  - Add atomic write for `rules.json` updates.
  - Add `updated_at` or loaded timestamp in response.
- `app/main.py`
  - Register admin router.
  - Protect `/ai/signals` and `/ai/recommendations` with admin auth or move them under `/admin/ai`.

### Acceptance Criteria

- Admin endpoints return `401` or `403` without a valid admin key.
- Valid rules can be applied and immediately affect requests.
- Invalid rules are rejected without changing active rules.
- Rule reload refreshes in-memory config from disk.

### Tests

- Admin auth required.
- Rule validation success/failure.
- Rule update changes limit behavior.
- Failed update preserves previous active rules.

## 5. Phase 3: Observability and Reliability

### Objectives

- Show operational maturity without overbuilding.
- Make fail-open/fail-closed behavior visible.

### Proposed File Changes

- `app/observability/metrics.py`
  - Add counters for:
    - allowed requests
    - denied requests
    - Redis fail-open events
    - Redis fail-closed events
    - rule reloads
- `app/observability/logging.py`
  - Configure structured JSON logs or consistent key-value logs.
- `app/api/health.py`
  - Add:
    - `GET /health`
    - `GET /ready`
  - Keep rate-limited demo route separate, such as `/api/limited-health`, so platform health checks are not rate-limited.
- `app/main.py`
  - Add request ID middleware.
  - Add `GET /metrics`.

### Acceptance Criteria

- Redis readiness is visible from `/ready`.
- Metrics change after allowed, denied, and fail-open/fail-closed decisions.
- Logs include request ID, route, identifier hash, decision, remaining tokens, and fail mode.

### Tests

- `/ready` reports healthy with fake Redis.
- `/metrics` includes expected metric names.
- Request ID is present in response headers.
- Telemetry does not expose raw API keys when identifier hashing is enabled.

## 6. Phase 4: Demo Dashboard

### Objectives

- Make the project easy to understand visually.
- Avoid adding a heavy frontend stack unless the project later needs it.

### Recommended Approach

Use FastAPI static files plus one lightweight HTML/CSS/JavaScript page:

- `app/static/demo.html`
- `app/static/demo.css`
- `app/static/demo.js`
- Route: `GET /demo`

### Demo Features

- API key selector:
  - Anonymous/IP client
  - Free client
  - Premium client
  - Abusive client
- Endpoint selector:
  - `/api/data`
  - `/api/limited-health`
- Send single request button.
- Burst request button.
- Response timeline with status, remaining tokens, and retry-after.
- Live signals panel.
- Recommendations panel.
- Admin rule viewer in read-only mode by default.

### Acceptance Criteria

- Dashboard works from Docker Compose at `http://localhost:8000/demo`.
- User can trigger a `429` visibly.
- User can generate recommendations after traffic.
- UI displays enough rate-limit headers to explain behavior.

### Tests/Checks

- Basic integration test that `/demo` returns HTML.
- Manual browser check for:
  - Desktop layout
  - Mobile layout
  - Burst request behavior
  - Signals refresh

## 7. Phase 5: CI, Quality, and Portfolio Polish

### Objectives

- Make the repository look maintained and reviewable.
- Add confidence checks without slowing down the learning flow.

### Tasks

- Add `ruff` or `black` configuration.
- Add GitHub Actions workflow:
  - Install dependencies
  - Run tests
  - Run lint
  - Optional coverage report
- Add `.env.example`.
- Add `Makefile` or task commands:
  - `make dev`
  - `make test`
  - `make lint`
  - `make compose-up`
- Add load-test script:
  - Simple Python/httpx script or k6 example.
- Add screenshots or GIFs after dashboard exists. (Implemented in Phase 11)

### Acceptance Criteria

- CI passes on pull requests.
- README badges reflect real checks.
- New contributors can run local tests with one documented command.

## 8. Suggested Backlog

### Original MVP Backlog

The original MVP and follow-up backlog has been implemented through Phase 35. Completed work includes limiter correctness, admin APIs, dashboard, metrics, tracing, persistent telemetry, CI/security checks, rule history, policy dry runs, multiple algorithms, proxy trust, templated route keys, rule metadata, sensitive-rule approval workflow, optional SQLite-backed rule storage, pending-approval dashboard controls, a filtered rule-change audit view, a Redis outage demo script, recommendation-to-dry-run policy drafts, documented load-test benchmark output, CI coverage reporting, sliding-window rate limiting, multiple named admin keys with safe key-name introspection, rule import/export helpers, and OpenAPI examples for admin workflows.

### P0: Next Implementation Candidates

- No P0 implementation candidates remain from the AI research queue.

### P1: Product And Demo Polish

- P1 AI research queue is complete.

### P2: Advanced Platform Enhancements

- P2 AI research queue is complete through AI-P5.

## 9. AI Research Upgrade

The AI research track extends the completed control-plane work into a safe advisor system. The detailed backlog lives in [AI_RESEARCH_ROADMAP.md](AI_RESEARCH_ROADMAP.md), and the architecture/data-model design lives in [AI_FEATURE_DESIGN.md](AI_FEATURE_DESIGN.md).

### Architecture Upgrade

AI should be a control-plane subsystem, not an enforcement dependency. The request path remains:

```text
FastAPI dependency -> RulesManager -> Redis Lua script -> response headers -> telemetry
```

The AI path consumes telemetry after decisions are made:

```text
Telemetry -> feature extraction -> advisors -> policy proposal -> validate -> dry-run -> approval -> apply/rollback
```

This keeps runtime behavior deterministic and gives every AI proposal the same safety controls as hand-written policy changes.

### New Modules

- `app/ai/features.py`: converts raw decisions into route, identifier, and route-identifier features.
- `app/ai/advisors.py`: deterministic advisor engines for tuning, abuse, reliability, and algorithm selection.
- `app/ai/simulation.py`: replay-based counterfactual policy simulator.
- `app/ai/anomalies.py`: deterministic anomaly detectors for spikes, retry loops, concentrated offenders, sensitive-route probing, and Redis outage exposure.
- `app/ai/copilot.py`: optional LLM adapter and policy-draft workflow, disabled by default, with fake and OpenAI-compatible HTTP providers.
- `scripts/ai_eval.py`: repeatable research evaluation scenarios and reports.
- `scripts/ai_live_eval.py`: live HTTP evaluation that compares Redis-backed response captures with the synthetic baseline.
- `scripts/ai_research_report.py`: compact Markdown report generator for synthetic, live, outage, and persisted evaluation summaries.
- `scripts/ai_ci_dry_run.py`: CI-friendly wrapper that produces synthetic, seeded SQLite persisted, and research-report artifacts without live services.

### Implementation Sequence

1. Extend telemetry data capture and persistence.
2. Build feature extraction with deterministic tests.
3. Replace threshold-only recommendations with advisor v2.
4. Upgrade dry-run with replay simulation.
5. Add anomaly detection and dashboard visibility.
6. Add optional LLM copilot behind explicit configuration.
7. Add evaluation scenarios and document research results.
8. Harden the copilot provider boundary with a real HTTP adapter while preserving offline fake-provider tests.
9. Add a live HTTP evaluation harness for running-app comparison against the synthetic AI baseline.
10. Add persisted telemetry replay windows for real demo-run evaluation reports.
11. Add opt-in Redis outage mode to the live evaluator for end-to-end reliability-scenario coverage.
12. Add a generated research report artifact that combines available AI evaluation summaries.
13. Add a CI-friendly AI dry-run artifact path that does not require Docker, Redis, network access, or a running app.
14. Expose the generated AI research report artifact through the admin API and demo dashboard.
15. Run the CI-friendly AI dry-run in GitHub Actions and upload its generated artifact bundle.

### Safety Requirements

- AI output must never apply rules directly.
- Generated policies must pass validation before dry-run.
- Sensitive-route changes must use pending approval.
- Recommendations must include confidence, rationale, signals, expected impact, and safety notes.
- LLM prompts must avoid raw identifiers when `HASH_IDENTIFIERS=true`.
- Local tests must run without network or model-provider credentials.
- Provider calls must stay in admin control-plane endpoints and return provider failures without affecting enforcement traffic.

## 10. Proposed Milestones

### Milestone 1: Correct Core

- Limiter result object.
- Accurate `Retry-After`.
- Rule validation.
- Updated tests.

### Milestone 2: Control Plane

- Admin auth.
- Rule read/validate/update/reload endpoints.
- Protected AI endpoints.

### Milestone 3: Demo Experience

- `/demo` dashboard.
- Demo scenarios.
- README walkthrough.

### Milestone 4: Operational Story

- Metrics.
- Structured logs.
- Readiness endpoint.
- CI and quality checks.

## 11. Review Checklist

- Does the code still teach the token-bucket algorithm clearly?
- Can a reviewer trigger and understand `429` behavior quickly?
- Are internal endpoints protected?
- Are project claims honest and backed by code?
- Do tests cover concurrency, failure mode, and rule-management behavior?
- Are operational tradeoffs documented instead of hidden?

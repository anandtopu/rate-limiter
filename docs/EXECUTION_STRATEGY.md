# Execution Strategy: Portfolio Rate Limiter Upgrade

## 1. Strategy Overview

Implement the upgrade as a sequence of small, reviewable phases. Each phase should leave the project runnable, tested, and demoable before moving to the next one.

The safest implementation order is:

1. Establish baseline documentation and verification commands.
2. Fix limiter correctness and rule validation.
3. Add admin/security boundaries.
4. Add observability and reliability surfaces.
5. Build the demo dashboard.
6. Finish CI, docs, and portfolio polish.

This order keeps the core enforcement path trustworthy before exposing rule management, then makes behavior visible before adding the browser demo.

## 2. Working Principles

- Keep the token-bucket implementation readable and easy to explain.
- Prefer narrow changes with focused tests over broad refactors.
- Treat every phase as shippable: tests pass, Docker still starts, and README commands remain accurate.
- Protect internal/admin behavior before making it prominent in the UI.
- Document tradeoffs honestly instead of over-claiming production readiness.
- Use the existing lightweight FastAPI structure unless a phase clearly requires a new module.

## 3. Phase 0: Baseline and Documentation Cleanup

### Goal

Align public documentation with the product direction and verify the current local workflow.

### Implementation Steps

1. Run the current test suite and record the baseline state.
2. Confirm Docker Compose service names and startup command.
3. Update `README.md` language from "production-ready" to "production-inspired".
4. Add a short architecture section that matches the current app:
   - FastAPI route dependency
   - Redis Lua token bucket
   - JSON rules
   - in-memory telemetry
5. Add "Known Tradeoffs":
   - in-memory telemetry
   - JSON-backed rule storage
   - demo admin key
   - fail-open behavior
   - raw identifier handling until hashing is implemented
6. Add a "Portfolio Demo Walkthrough" section with commands that can be exercised now, then update it again after `/demo` exists.

### Exit Criteria

- README claims are accurate.
- Current tests pass or known failures are documented.
- Docker commands in README match `docker-compose.yml`.

### Suggested Commit

`docs: align portfolio positioning and baseline workflow`

## 4. Phase 1: Limiter Correctness and Rule Validation

### Goal

Make the enforcement path defensible in a technical review.

### Implementation Steps

1. Update [app/models/rules.py](../app/models/rules.py):
   - Enforce `rate > 0`.
   - Enforce `capacity > 0`.
   - Add `fail_mode: Literal["open", "closed"] = "open"`.
   - Add optional `description` and `tier` metadata.
2. Introduce a structured limiter result in [app/core/limiter.py](../app/core/limiter.py):
   - `allowed`
   - `remaining`
   - `retry_after_s`
   - `reset_timestamp`
   - `redis_failed`
   - `redis_fail_open`
3. Keep fractional token math inside Redis/Lua and only round at response boundaries.
4. Calculate `retry_after_s` from missing tokens for the current request, not from time to refill the whole bucket.
5. Update [app/api/depends.py](../app/api/depends.py):
   - Use the result object.
   - Centralize rate-limit header creation in one helper.
   - Apply rule-level `fail_mode`.
6. Update [rules.json](../rules.json) with metadata and explicit fail-mode examples.
7. Update tests:
   - invalid `rate` and `capacity`
   - accurate `Retry-After`
   - fail-open Redis failure
   - fail-closed Redis failure
   - existing race condition behavior

### Exit Criteria

- `429` responses include `Retry-After` equal to time until the next request can succeed.
- Invalid rule values fail validation.
- Fail-open and fail-closed behavior is covered by tests.
- Existing API behavior still works for `/health` and `/api/data`.

### Suggested Commit

`fix: harden limiter results and rule validation`

## 5. Phase 2: Admin API and Security Boundary

### Goal

Add a small authenticated control plane for rule inspection and updates.

### Implementation Steps

1. Update [app/config.py](../app/config.py):
   - `admin_api_key`
   - `rules_path`
   - `expose_demo_dashboard`
   - `hash_identifiers`
2. Add `app/api/security.py`:
   - Admin API key dependency.
   - Use a simple header such as `X-Admin-Key`.
   - Return consistent `401` or `403` errors.
3. Extend [app/core/rules.py](../app/core/rules.py):
   - `validate_rules(data)`
   - atomic write for rule updates
   - reload from `settings.rules_path`
   - response metadata such as `loaded_at`
4. Add `app/api/admin.py`:
   - `GET /admin/rules`
   - `POST /admin/rules/validate`
   - `PUT /admin/rules`
   - `POST /admin/rules/reload`
5. Register the admin router in [app/main.py](../app/main.py).
6. Protect internal AI endpoints:
   - Either require admin auth on `/ai/signals` and `/ai/recommendations`, or move them under `/admin/ai`.
   - Prefer keeping old paths temporarily with auth to reduce routing churn.
7. Add tests:
   - missing admin key rejected
   - invalid admin key rejected
   - valid rule validation succeeds
   - invalid rule validation fails
   - successful rule update changes request behavior
   - failed rule update preserves previous active rules

### Exit Criteria

- No internal/admin-like endpoint is exposed without an admin key.
- Valid rules can be applied immediately.
- Invalid rules are rejected without changing active runtime state.
- Rule reload refreshes from disk.

### Suggested Commit

`feat: add authenticated admin rule management`

## 6. Phase 3: Observability and Reliability

### Goal

Make operational behavior visible without adding heavy infrastructure.

### Implementation Steps

1. Add `app/observability/metrics.py`:
   - allowed request counter
   - denied request counter
   - Redis fail-open counter
   - Redis fail-closed counter
   - rule reload counter
2. Add `GET /metrics` in [app/main.py](../app/main.py):
   - Keep output Prometheus-compatible or simple text metrics.
3. Add `app/observability/logging.py`:
   - consistent structured key-value logs
   - include route, decision, fail mode, request ID, and hashed identifier when enabled
4. Add request ID middleware:
   - accept inbound `X-Request-ID` when present
   - generate one when missing
   - echo it in response headers
5. Split platform health from demo-limited health:
   - `GET /health` should be basic process health and not rate-limited.
   - `GET /ready` should check Redis readiness.
   - Add `GET /api/limited-health` as a rate-limited demo route.
6. Add safe identifier normalization/hashing:
   - use raw identifiers for rule override matching if needed
   - use hashed values for Redis keys and telemetry when `hash_identifiers` is enabled
7. Add tests:
   - `/ready` reports Redis state
   - `/metrics` includes expected metric names
   - request ID header exists
   - telemetry does not expose raw API keys when hashing is enabled
   - limited health remains rate-limited

### Exit Criteria

- Redis readiness is visible.
- Metrics change after allow, deny, fail-open, and fail-closed outcomes.
- Logs and telemetry avoid exposing raw identifiers when configured.
- Platform health checks cannot be exhausted by rate limits.

### Suggested Commit

`feat: add health readiness metrics and request tracing`

## 7. Phase 4: Demo Dashboard

### Goal

Make the project understandable from a browser in under five minutes.

### Implementation Steps

1. Add lightweight static assets:
   - `app/static/demo.html`
   - `app/static/demo.css`
   - `app/static/demo.js`
2. Serve `GET /demo` from FastAPI when `settings.expose_demo_dashboard` is true.
3. Add dashboard controls:
   - API key selector: anonymous, free, premium, abusive
   - endpoint selector: `/api/data`, `/api/limited-health`
   - single request button
   - burst request button
   - admin key input for protected signals/recommendations
4. Display live results:
   - status code
   - response body
   - `X-RateLimit-Limit`
   - `X-RateLimit-Remaining`
   - `X-RateLimit-Reset`
   - `Retry-After`
5. Add panels:
   - recent request timeline
   - signals snapshot
   - generated recommendations
   - read-only active rule viewer
6. Add tests/checks:
   - `/demo` returns HTML when enabled
   - `/demo` is hidden or disabled when configured off
   - manual desktop and mobile browser pass
   - burst request visibly produces `429`

### Exit Criteria

- `http://localhost:8000/demo` works with Docker Compose.
- A reviewer can trigger a `429` without using curl.
- Signals and recommendations are understandable from the UI.
- The UI remains static and lightweight, with no frontend build step.

### Suggested Commit

`feat: add interactive rate limiter demo dashboard`

## 8. Phase 5: CI, Quality, and Portfolio Polish

### Goal

Make the repository easy to review, run, and trust.

### Implementation Steps

1. Add formatting/linting:
   - choose `ruff` for fast linting and formatting, or pair `black` with a minimal linter
   - add config to `pyproject.toml` if one does not exist
2. Add task commands:
   - `make dev`
   - `make test`
   - `make lint`
   - `make compose-up`
3. Add `.env.example`:
   - `REDIS_URL`
   - `ADMIN_API_KEY`
   - `RULES_PATH`
   - `EXPOSE_DEMO_DASHBOARD`
   - `HASH_IDENTIFIERS`
4. Add GitHub Actions:
   - install dependencies
   - run tests
   - run lint
   - optional coverage artifact
5. Add a load-test script:
   - simple Python/httpx script is enough
   - include free/premium/abusive examples
6. Finalize README:
   - badges only for checks that exist
   - architecture diagram
   - demo walkthrough
   - security/tradeoff notes
   - screenshots or GIFs after the dashboard exists

### Exit Criteria

- A new contributor can run tests with one documented command.
- CI passes on pull requests.
- README accurately reflects implemented features.
- Demo assets and docs show the completed portfolio story.

### Suggested Commit

`chore: add ci quality checks and portfolio polish`

## 9. Cross-Phase Risk Register

| Risk | Phase | Mitigation |
| --- | --- | --- |
| `Retry-After` changes break current assertions | Phase 1 | Update tests to assert behavior, not old implementation details. |
| Rule updates corrupt `rules.json` | Phase 2 | Validate before write and use atomic temp-file replacement. |
| Admin key leaks into demo code | Phase 2/4 | Let users enter it locally; do not hard-code secrets in static JS. |
| Health endpoint gets rate-limited by mistake | Phase 3 | Keep `/health` unprotected and move limited demo behavior to `/api/limited-health`. |
| Identifier hashing breaks override matching | Phase 3 | Match overrides before hashing; hash only storage/telemetry keys. |
| Demo dashboard grows into an app rewrite | Phase 4 | Keep static HTML/CSS/JS and avoid a frontend toolchain. |
| CI introduces dependency churn | Phase 5 | Add minimal tooling and pin only what is needed. |

## 10. Recommended Review Gates

After each phase:

1. Run the test suite.
2. Start the app locally or with Docker Compose.
3. Manually hit one allowed request and one denied request.
4. Confirm README/docs still match the implemented behavior.
5. Commit the phase before starting the next one.

Minimum command set once Phase 5 exists:

```bash
make test
make lint
make compose-up
```

Until then, use the current direct commands:

```bash
./.venv/Scripts/pytest -q
docker-compose up --build
```

## 11. Suggested Implementation Timeline

| Order | Phase | Expected Scope | Dependency |
| --- | --- | --- | --- |
| 1 | Phase 0 | Docs and baseline checks | None |
| 2 | Phase 1 | Core correctness | Phase 0 |
| 3 | Phase 2 | Admin APIs and auth | Phase 1 |
| 4 | Phase 3 | Metrics, health, logging | Phase 1 and Phase 2 security decisions |
| 5 | Phase 4 | Demo dashboard | Phase 2 and Phase 3 surfaces |
| 6 | Phase 5 | CI and polish | All product behavior implemented |

## 12. Definition of Done

The full upgrade is complete when:

- `docker compose up --build` starts the API, Redis, and dashboard.
- `GET /demo` loads an interactive dashboard.
- Protected routes emit accurate rate-limit headers.
- Exhausted buckets return `429` with accurate `Retry-After`.
- Admin endpoints reject missing or invalid admin keys.
- Invalid rules cannot be applied.
- Metrics, signals, and recommendations reflect request activity.
- The test suite and lint checks pass.
- README presents the project as production-inspired, demo-ready, and honest about tradeoffs.

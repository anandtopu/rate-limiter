# AI Feature Design

## Summary

The AI feature set turns the rate limiter into a research platform for safe policy advice. AI does not decide whether an individual request is allowed. Instead, it studies telemetry after decisions are made and produces explainable policy recommendations for admins.

## System Boundary

### In Scope

- Feature extraction from recent and persisted telemetry.
- Deterministic advisor engines.
- Replay-based policy simulation.
- Anomaly and abuse detection.
- Optional LLM explanation and policy-draft assistance.
- Evaluation scripts and documented research results.

### Out Of Scope

- Model calls inside `rate_limit`.
- Automatic application of AI-generated rules.
- Replacing Redis Lua enforcement with probabilistic decisions.
- Production-grade ML infrastructure or feature stores.

## Architecture

```text
app/api/depends.py
  records RateLimitEvent
        |
        v
app/ai/telemetry.py
  in-memory window + optional SQLite store
        |
        v
app/ai/features.py
  route features
  identifier features
  route-identifier features
        |
        v
app/ai/advisors.py
  tuning advisor
  abuse advisor
  reliability advisor
  algorithm advisor
        |
        v
app/ai/simulation.py
  counterfactual dry-run replay
        |
        v
admin APIs and dashboard
  validate -> dry-run -> approval -> apply -> rollback
```

## Data Model Upgrade

Extend `RateLimitEvent` beyond the current fields:

- Existing: `timestamp`, `route_path`, `identifier`, `allowed`, `remaining`, `capacity`, `rate`, `retry_after_s`, `redis_fail_open`.
- Add: `algorithm`, `fail_mode`, `tier`, `owner`, `sensitivity`, `rule_version`, `method`, `status_code`, `latency_ms`.

SQLite telemetry should migrate old databases by adding nullable columns. Old rows should remain readable, with missing fields treated as unknown.

## Feature Model

`app/ai/features.py` should expose deterministic functions such as:

- `build_route_features(events, rules)`.
- `build_identifier_features(events)`.
- `build_route_identifier_features(events)`.
- `build_reliability_features(events, rules)`.

Recommended feature fields:

- request count,
- denial count and denial ratio,
- unique identifier count,
- top offender concentration,
- retry-after distribution,
- remaining-token pressure,
- Redis fail-open count,
- sensitivity/fail-mode exposure,
- current rule rate/capacity/algorithm,
- sample size and confidence hints.

## Recommendation Schema

Advisor output should use a common schema:

```json
{
  "id": "rec_...",
  "type": "tuning|abuse|reliability|algorithm",
  "route": "/api/data",
  "severity": "low|medium|high",
  "confidence": 0.82,
  "signals": {},
  "rationale": "Human-readable explanation.",
  "proposed_change": {},
  "expected_impact": {},
  "safety_notes": [],
  "created_at": 1734000000
}
```

## API Upgrade Plan

- Keep `GET /ai/signals` as a compact live summary.
- Upgrade `POST /ai/recommendations` to return advisor-v2 recommendations.
- Keep `POST /admin/rules/recommendation-draft`, but make it consume advisor-v2 `proposed_change`.
- Extend `POST /admin/rules/dry-run` with replay simulation details.
- Add `GET /admin/ai/anomalies` and include anomaly findings in the signals response.
- Add optional `POST /admin/ai/policy-copilot` after deterministic advisors and simulation are stable.

## Dashboard Upgrade Plan

- Add an AI feature summary panel with route-level pressure and top offender concentration.
- Replace raw recommendation output with recommendation cards or summarized JSON.
- Add replay impact summary to dry-run output.
- Add anomaly findings with evidence and suggested next actions.
- Keep the JSON output visible for research/debugging.

## Testing Strategy

- Unit-test feature extraction with hand-built events.
- Unit-test each advisor with normal, abusive, sensitive, and outage scenarios.
- Add API tests for recommendation schema compatibility.
- Add dry-run replay tests with deterministic event sequences.
- Add fake LLM adapter tests when copilot work starts.
- Add provider adapter tests with mocked HTTP responses so local tests never require network or credentials.
- Extend load-test/eval scripts for repeatable research scenarios.

## Rollout Strategy

1. Ship enriched telemetry and feature extraction behind existing endpoints.
2. Introduce advisor v2 while preserving old recommendation fields where useful.
3. Add replay dry-run and dashboard summaries.
4. Add anomaly APIs and scenario tests. (Done in AI-P3.)
5. Add optional LLM copilot with fake adapter tests. (Done in AI-P4; OpenAI-compatible HTTP adapter added in AI-H2.)
6. Publish evaluation results and limitations. (Done in AI-P5.)

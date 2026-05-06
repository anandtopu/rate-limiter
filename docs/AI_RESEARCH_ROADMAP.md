# AI Research Roadmap

## Purpose

This roadmap converts the AI review into an implementation backlog for evolving the rate limiter into an AI-assisted control-plane research project.

The core rule is simple: AI must not sit in the request enforcement path. The Redis-backed limiter remains deterministic and low-latency. AI features analyze telemetry, draft recommendations, explain tradeoffs, and produce validated policy proposals that flow through dry-run, audit, approval, import/export, and rollback controls.

Detailed architecture and data-model design are tracked in [AI_FEATURE_DESIGN.md](AI_FEATURE_DESIGN.md).

## Current Baseline

The application already has the foundations needed for AI-assisted rate-limit tuning:

- Structured rate-limit decision telemetry in `app/ai/telemetry.py`.
- Optional SQLite persistence in `app/observability/telemetry_store.py`.
- Rule metadata for `tier`, `owner`, and `sensitivity`.
- Rule dry-run, history, audit, import/export, rollback, and pending approval APIs.
- Recommendation-to-draft flow at `POST /admin/rules/recommendation-draft`.
- Dashboard panels for signals, persisted telemetry, recommendations, anomalies, policy copilot, dry runs, rule history, audit, and approvals.

The current AI layer is control-plane only. It extracts telemetry features, produces advisor recommendations, replays policy drafts, detects anomalies, and can run an optional policy copilot for local explanation and draft-validation workflows. The copilot defaults to a deterministic fake adapter for tests and can opt into an OpenAI-compatible HTTP adapter for demos.

## Design Principles

- Keep enforcement deterministic, auditable, and free of external model calls.
- Treat AI output as advice, not authority.
- Validate every generated policy with existing Pydantic rule models.
- Run every proposed policy through dry-run before it can be applied.
- Send sensitive changes through the second-admin approval workflow.
- Preserve explainability: every recommendation needs signals, confidence, expected impact, and rollback guidance.
- Prefer deterministic heuristics before introducing ML or LLM dependencies.
- Make datasets and evaluations repeatable so research claims are measurable.

## Target Architecture

```text
Request
  |
  v
FastAPI rate_limit dependency
  |
  v
Redis limiter scripts
  |
  v
Decision telemetry
  |
  +--> In-memory signal window
  |
  +--> SQLite event store
          |
          v
     Feature extractor
          |
          v
     Advisor engines
       - deterministic tuning advisor
       - anomaly and abuse detector
       - reliability advisor
       - optional LLM explainer/copilot
          |
          v
     Policy proposal
          |
          v
Validate -> Dry-run replay -> Audit -> Approval -> Apply/Rollback
```

## Backlog

### AI-P0: Telemetry Feature Foundation

Status: Done.

Goal: make telemetry rich enough for AI features to reason about behavior without guessing.

Coding tasks:

- Extend `RateLimitEvent` with `algorithm`, `fail_mode`, `tier`, `owner`, `sensitivity`, `rule_version`, `method`, `status_code`, and optional `latency_ms`.
- Add a SQLite migration path for the telemetry table without breaking existing demo databases.
- Persist the new fields in `SQLiteTelemetryStore.record`.
- Return new fields from `recent`, `summary`, and `analytics` where useful.
- Add `app/ai/features.py` with route, identifier, and route-identifier feature extraction.
- Add tests for enriched event recording, persisted reads, disabled persistence, and migration from the old schema.

Acceptance criteria:

- Existing request behavior remains unchanged.
- `/ai/signals` and `/admin/telemetry/persistent` expose enough context for route-level AI analysis.
- Tests demonstrate feature extraction for normal, abusive, sensitive, and Redis-fail-open traffic.

### AI-P1: Advisor V2

Status: Done.

Goal: replace the threshold-only recommendation layer with structured, explainable advisors.

Coding tasks:

- Add `app/ai/advisors.py` with separate deterministic advisors:
  - tuning advisor for over-denial or under-provisioned routes,
  - abuse advisor for concentrated offender patterns,
  - reliability advisor for fail-open exposure on sensitive routes,
  - algorithm advisor for fixed-window vs sliding-window vs token-bucket suitability.
- Add a common recommendation schema with `id`, `type`, `route`, `severity`, `confidence`, `signals`, `rationale`, `proposed_change`, `expected_impact`, and `safety_notes`.
- Update `/ai/recommendations` to return advisor output while preserving backward-compatible fields where possible.
- Update `draft_from_recommendations` to consume the new schema.
- Add tests for each advisor and for no-op cases.

Acceptance criteria:

- Recommendations are explainable and stable across repeated runs with the same telemetry.
- Advisor output can still create editable policy drafts and dry-run reports.
- Sensitive recommendations do not bypass approval.

### AI-P2: Replay-Based Counterfactual Dry Run

Status: Done.

Goal: make policy dry-runs more realistic by replaying observed decisions instead of using rough request counts.

Coding tasks:

- Add a replay simulator in `app/ai/simulation.py`.
- Support both in-memory recent events and persisted telemetry windows.
- Estimate allowed, denied, newly denied, newly allowed, route impact, identifier impact, and sensitive-route impact.
- Add query/body controls for time range, event limit, and simulation mode.
- Update `POST /admin/rules/dry-run` to include replay output when event history is available.
- Add dashboard rendering for replay impact.

Acceptance criteria:

- Dry-run reports show route and identifier-level counterfactuals.
- The simulator is deterministic for a fixed event sequence.
- Invalid rules still fail before simulation.

### AI-P3: Anomaly And Abuse Detection

Status: Done.

Goal: detect suspicious traffic patterns that a basic 429-ratio heuristic misses.

Coding tasks:

- Add anomaly detectors for:
  - sudden route traffic spikes,
  - high denial concentration from one identifier,
  - retry-loop behavior after `429`,
  - sensitive-route probing,
  - Redis outage exposure.
- Add `/admin/ai/anomalies` or include anomaly findings in `/ai/signals`.
- Add dashboard panel for anomaly summaries and recommended next actions.
- Add tests and load-test scenarios for normal, bursty, abusive, and retry-loop traffic.

Acceptance criteria:

- Normal premium bursts are not mislabeled as abuse in baseline scenarios.
- Abusive and retry-loop scenarios produce clear findings with evidence.
- Findings include suggested policy actions but do not apply them automatically.

### AI-P4: LLM Policy Copilot

Status: Done.

Goal: add optional natural-language assistance for explaining telemetry and drafting safe policy changes.

Coding tasks:

- Add configuration for optional LLM use, disabled by default.
- Add an adapter interface so the rest of the app does not depend on a specific provider.
- Add an endpoint such as `POST /admin/ai/policy-copilot`.
- Inputs should include a user prompt, active rules, feature summaries, recommendations, and safety constraints.
- Outputs should include explanation text plus optional rule JSON.
- Validate and dry-run any generated rule JSON before returning it.
- Add tests with a fake LLM adapter.

Acceptance criteria:

- The feature is fully optional and does not affect offline/local test runs.
- LLM output cannot directly mutate active rules.
- Invalid LLM-generated JSON is reported safely.

Implemented result:

- `POST /admin/ai/policy-copilot` is disabled by default and remains outside the request enforcement path.
- The `fake` provider supports deterministic local tests and draft-validation workflows.
- The `openai_compatible` provider posts chat-completions-style JSON to `AI_COPILOT_ENDPOINT`, adds `AI_COPILOT_API_KEY` as an optional bearer token, and parses provider JSON into explanation text plus optional rule JSON.
- Provider runtime failures return `502`; disabled or missing provider configuration returns `503`.
- Any returned rule JSON still goes through existing validation and dry-run before being shown to the admin.

### AI-P5: Research Evaluation Harness

Status: Done.

Goal: make AI feature quality measurable and repeatable.

Coding tasks:

- Extend `scripts/load_test.py` or add `scripts/ai_eval.py` with repeatable traffic scenarios:
  - normal free traffic,
  - premium bursts,
  - abusive identifier,
  - retry loop,
  - sensitive-route probing,
  - Redis outage,
  - mixed workload.
- Save expected labels and expected recommendation types.
- Add a report format with recommendation precision, false-positive notes, denied-legitimate estimate, abuse-reduction estimate, and policy stability.
- Document representative results in README or a research report.

Acceptance criteria:

- Running the evaluation script produces deterministic scenario output.
- Advisor regressions are visible in tests or generated reports.
- Documentation states the limits of the research results honestly.

Implemented result:

- `scripts/ai_eval.py` runs labeled synthetic scenarios for normal free traffic, premium bursts, abusive identifiers, retry loops, route spikes, sensitive-route probing, Redis outage exposure, fixed-window pressure, and mixed workloads.
- The report includes recommendation/anomaly precision and recall, false-positive notes, denied-legitimate estimates, abuse-reduction estimates, policy-stability status, and limitations.
- Representative output currently reports `recommendation_precision: 1.0`, `recommendation_recall: 1.0`, `anomaly_precision: 1.0`, `anomaly_recall: 1.0`, and `policy_stability: "stable"` after advisor hardening suppresses route-wide tuning when denials are dominated by concentrated abuse.
- `scripts/ai_eval.py --telemetry-db ...` replays persisted SQLite telemetry windows from real demo runs and can optionally compare the observed labels with a named synthetic scenario.
- `scripts/ai_live_eval.py` complements the synthetic harness by sending HTTP traffic to a running app, rebuilding evaluation events from rate-limit headers and status codes, and comparing live observed labels with the synthetic baseline. Redis outage exposure remains opt-in through `--include-redis-outage` because it intentionally stops or assumes unavailable Redis.
- `scripts/ai_research_report.py` generates a compact Markdown report artifact from the deterministic synthetic baseline plus optional saved live, outage, and persisted evaluation JSON.
- `scripts/ai_ci_dry_run.py` runs the CI-safe path: deterministic synthetic evaluation, a seeded local SQLite persisted replay, and a combined research report without Docker, Redis, network calls, or a running app.
- `GET /admin/ai/research-report` and the dashboard AI Research Report panel expose the configured Markdown artifact through the protected admin control plane.
- GitHub Actions runs the CI-safe dry-run command and uploads the generated report bundle as the `ai-ci-dry-run` artifact.
- `GET /admin/ai/research-report?format=markdown&download=true` returns the configured Markdown artifact as a downloadable `text/markdown` response for review workflows.
- The AI CI dry-run artifact bundle includes `MANIFEST.md` and `manifest.json` so CI reviewers can quickly find report files, statuses, byte counts, and limitations.
- The dashboard AI Research Report panel can download the raw Markdown artifact using the current admin key.
- CI artifact reviewer guidance now points to `coverage-xml`, `cyclonedx-sbom`, and the `ai-ci-dry-run` manifest entrypoints.
- Report JSON metadata includes a canonical `download_url`, and the dashboard surfaces it alongside the loaded report metadata.
- The dashboard download path reads the server-provided filename from `Content-Disposition` and reports the saved filename plus byte count.
- `scripts/ai_ci_dry_run.py --list-scenarios` lists seeded persisted replay fixtures with event counts and expected labels.

## Documentation Tasks

- Keep this roadmap as the authoritative AI backlog.
- Update `README.md` when a phase becomes user-visible.
- Keep `docs/BACKLOG_STATUS.md` synchronized with current AI phase status.
- Extend `docs/IMPLEMENTATION_PLAN.md` with implementation sequencing.
- Add or update OpenAPI examples for new AI admin endpoints.
- Document safety boundaries for AI-generated policies.

## Risks And Guardrails

- Risk: AI recommendations overfit small demo traffic.
  Guardrail: include confidence, minimum sample sizes, and no-op recommendations.
- Risk: generated rules deny legitimate traffic.
  Guardrail: require dry-run impact, audit metadata, and approval for sensitive changes.
- Risk: telemetry contains sensitive identifiers.
  Guardrail: preserve `HASH_IDENTIFIERS=true`, avoid raw identifiers in model prompts by default, and document prompt-redaction rules.
- Risk: LLM dependency makes local demos fragile.
  Guardrail: keep LLM features optional and provide deterministic fake adapters for tests.
- Risk: AI work bloats the readable portfolio app.
  Guardrail: isolate AI modules under `app/ai` and keep enforcement modules unchanged.

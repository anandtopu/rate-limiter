# AI Rate Limiter Research Report

## Summary

- Overall status: `stable`
- Sections provided: `1`

## Synthetic Baseline

- Status: `stable`
- scenarios: `9`
- stable_scenarios: `9`
- recommendation_precision: `1.0`
- recommendation_recall: `1.0`
- anomaly_precision: `1.0`
- anomaly_recall: `1.0`
- denied_legitimate_estimate: `10`
- abuse_reduction_estimate: `20`

Notes:
- Synthetic events exercise advisor logic, not end-to-end Redis timing.
- Precision and recall are label-level checks against hand-authored expectations.
- Abuse-reduction estimates are based on denied abusive requests, not live mitigation.

## Live HTTP Comparison

- Status: `not_provided`

Notes:
- Live HTTP comparison JSON was not supplied.

## Redis Outage Live Coverage

- Status: `not_provided`

Notes:
- Redis outage live comparison JSON was not supplied.

## Persisted Telemetry Replay

- Status: `not_provided`

Notes:
- Persisted telemetry replay JSON was not supplied.

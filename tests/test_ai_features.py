from app.ai.features import (
    build_feature_summary,
    build_identifier_features,
    build_route_features,
    build_route_identifier_features,
)
from app.ai.telemetry import RateLimitEvent


def event(
    *,
    route_path: str = "/api/data",
    identifier: str = "free_user",
    allowed: bool = True,
    redis_fail_open: bool = False,
    algorithm: str = "token_bucket",
    fail_mode: str = "open",
    tier: str = "free",
    owner: str = "api-platform",
    sensitivity: str = "internal",
) -> RateLimitEvent:
    return RateLimitEvent(
        timestamp=100.0,
        route_path=route_path,
        identifier=identifier,
        allowed=allowed,
        remaining=4 if allowed else 0,
        capacity=5,
        rate=1.0,
        retry_after_s=None if allowed else 1,
        redis_fail_open=redis_fail_open,
        algorithm=algorithm,
        fail_mode=fail_mode,
        tier=tier,
        owner=owner,
        sensitivity=sensitivity,
        rule_version=3,
        method="GET",
        status_code=200 if allowed else 429,
    )


def test_route_features_summarize_pressure_and_metadata():
    features = build_route_features([
        event(identifier="free_user", allowed=True),
        event(identifier="free_user", allowed=False),
        event(identifier="free_user", allowed=False),
        event(identifier="premium_user", allowed=True),
        event(
            route_path="/api/accounts/{account_id}/data",
            identifier="account_probe",
            allowed=True,
            redis_fail_open=True,
            algorithm="sliding_window",
            fail_mode="closed",
            tier="enterprise",
            owner="accounts",
            sensitivity="sensitive",
        ),
    ])

    data_route = next(item for item in features if item["route"] == "/api/data")
    assert data_route["requests"] == 4
    assert data_route["denied"] == 2
    assert data_route["denial_ratio"] == 0.5
    assert data_route["unique_identifiers"] == 2
    assert data_route["top_identifier"] == "free_user"
    assert data_route["top_identifier_concentration"] == 0.75
    assert data_route["algorithms"] == ["token_bucket"]
    assert data_route["fail_modes"] == ["open"]
    assert data_route["owners"] == ["api-platform"]
    assert data_route["sensitivities"] == ["internal"]
    assert data_route["methods"] == ["GET"]
    assert data_route["status_codes"] == [200, 429]
    assert data_route["max_retry_after_s"] == 1
    assert data_route["latest_rule_version"] == 3

    sensitive_route = next(
        item for item in features if item["route"] == "/api/accounts/{account_id}/data"
    )
    assert sensitive_route["redis_fail_open"] == 1
    assert sensitive_route["algorithms"] == ["sliding_window"]
    assert sensitive_route["sensitivities"] == ["sensitive"]


def test_identifier_and_pair_features_rank_offenders():
    events = [
        event(identifier="abusive_user", allowed=False),
        event(identifier="abusive_user", allowed=False),
        event(identifier="abusive_user", allowed=True),
        event(identifier="normal_user", allowed=True),
    ]

    identifier_features = build_identifier_features(events)
    assert identifier_features[0]["identifier"] == "abusive_user"
    assert identifier_features[0]["requests"] == 3
    assert identifier_features[0]["denied"] == 2
    assert identifier_features[0]["denial_ratio"] == 0.6667

    pair_features = build_route_identifier_features(events)
    assert pair_features[0]["route"] == "/api/data"
    assert pair_features[0]["identifier"] == "abusive_user"
    assert pair_features[0]["denied"] == 2


def test_feature_summary_accepts_persisted_event_dicts():
    summary = build_feature_summary([
        {
            "route_path": "/api/data",
            "identifier": "persisted_user",
            "allowed": False,
            "remaining": 0,
            "capacity": 5,
            "rate": 1.0,
            "retry_after_s": 1,
            "redis_fail_open": False,
            "algorithm": "token_bucket",
            "fail_mode": "open",
            "tier": "free",
            "owner": "api-platform",
            "sensitivity": "internal",
            "rule_version": 2,
            "method": "GET",
            "status_code": 429,
        }
    ])

    assert summary["events_analyzed"] == 1
    assert summary["routes"][0]["route"] == "/api/data"
    assert summary["identifiers"][0]["identifier"] == "persisted_user"
    assert summary["route_identifiers"][0]["denial_ratio"] == 1.0

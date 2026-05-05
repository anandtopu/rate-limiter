from app.ai.advisors import (
    abuse_advisor,
    algorithm_advisor,
    generate_advisor_recommendations,
    reliability_advisor,
    tuning_advisor,
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
        tier="free",
        owner="api-platform",
        sensitivity=sensitivity,
        rule_version=2,
        method="GET",
        status_code=200 if allowed else 429,
    )


def test_tuning_advisor_returns_structured_scale_recommendation():
    recommendations = generate_advisor_recommendations(
        [event(allowed=index < 10, identifier=f"user_{index % 4}") for index in range(25)],
        generated_at=123,
    )

    tuning = next(item for item in recommendations["items"] if item["type"] == "tuning")
    assert recommendations["schema_version"] == 2
    assert tuning["id"] == "rec_tuning_api_data"
    assert tuning["severity"] == "high"
    assert 0 < tuning["confidence"] <= 1
    assert tuning["signals"]["rate_limited_ratio"] == 0.6
    assert tuning["proposed_change"]["kind"] == "scale_route_limit"
    assert tuning["expected_impact"]["direction"] == "reduce_denials"
    assert tuning["recommendation"]["action"] == "review_limits"


def test_tuning_advisor_suppresses_route_tuning_when_abuse_dominates_pressure():
    recommendations = generate_advisor_recommendations(
        [
            *[event(identifier=f"normal_user_{index}", allowed=True) for index in range(10)],
            *[event(identifier="abusive_user", allowed=index < 3) for index in range(10)],
        ],
        generated_at=123,
    )

    recommendation_types = {item["type"] for item in recommendations["items"]}

    assert "abuse" in recommendation_types
    assert "tuning" not in recommendation_types


def test_abuse_advisor_flags_concentrated_identifier_pressure():
    feature_summary = generate_advisor_recommendations(
        [
            *[event(identifier="abusive_user", allowed=False) for _ in range(5)],
            *[event(identifier="normal_user", allowed=True) for _ in range(5)],
        ],
        generated_at=123,
    )["feature_summary"]

    abuse = abuse_advisor(feature_summary)

    assert abuse[0]["type"] == "abuse"
    assert abuse[0]["signals"]["identifier"] == "abusive_user"
    assert abuse[0]["proposed_change"]["kind"] == "add_identifier_override"
    assert abuse[0]["proposed_change"]["identifier"] == "abusive_user"
    assert abuse[0]["recommendation"]["action"] == "review_identifier_override"


def test_reliability_advisor_recommends_fail_closed_for_sensitive_fail_open():
    feature_summary = generate_advisor_recommendations(
        [
            event(
                route_path="/api/accounts/{account_id}/data",
                identifier="account_user",
                allowed=True,
                redis_fail_open=True,
                algorithm="sliding_window",
                fail_mode="open",
                sensitivity="sensitive",
            )
        ],
        generated_at=123,
    )["feature_summary"]

    reliability = reliability_advisor(feature_summary)

    assert reliability[0]["type"] == "reliability"
    assert reliability[0]["severity"] == "high"
    assert reliability[0]["proposed_change"] == {
        "kind": "set_fail_mode",
        "route": "/api/accounts/{account_id}/data",
        "fail_mode": "closed",
    }
    assert "approval" in " ".join(reliability[0]["safety_notes"]).lower()


def test_algorithm_advisor_recommends_sliding_window_for_broad_fixed_window_pressure():
    events = [
        event(
            route_path="/api/limited-health",
            identifier=f"user_{index % 10}",
            allowed=index < 10,
            algorithm="fixed_window",
            fail_mode="closed",
            sensitivity="public",
        )
        for index in range(25)
    ]
    feature_summary = generate_advisor_recommendations(events, generated_at=123)["feature_summary"]

    algorithm = algorithm_advisor(feature_summary)

    assert algorithm[0]["type"] == "algorithm"
    assert algorithm[0]["proposed_change"] == {
        "kind": "set_algorithm",
        "route": "/api/limited-health",
        "algorithm": "sliding_window",
    }
    assert algorithm[0]["recommendation"]["action"] == "review_algorithm"


def test_advisors_return_noop_for_low_sample_normal_traffic():
    feature_summary = generate_advisor_recommendations(
        [event(identifier=f"user_{index}", allowed=True) for index in range(4)],
        generated_at=123,
    )["feature_summary"]

    assert tuning_advisor(feature_summary) == []
    assert abuse_advisor(feature_summary) == []
    assert reliability_advisor(feature_summary) == []
    assert algorithm_advisor(feature_summary) == []

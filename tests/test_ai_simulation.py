from app.ai.simulation import replay_policy
from app.ai.telemetry import RateLimitEvent
from app.models.rules import RateLimitConfig


def event(
    *,
    timestamp: float,
    route_path: str = "/api/data",
    identifier: str = "free_user",
    allowed: bool = True,
    sensitivity: str = "internal",
) -> RateLimitEvent:
    return RateLimitEvent(
        timestamp=timestamp,
        route_path=route_path,
        identifier=identifier,
        allowed=allowed,
        remaining=1 if allowed else 0,
        capacity=2,
        rate=1.0,
        retry_after_s=None if allowed else 1,
        redis_fail_open=False,
        algorithm="token_bucket",
        fail_mode="open",
        tier="free",
        owner="api-platform",
        sensitivity=sensitivity,
        rule_version=1,
        method="GET",
        status_code=200 if allowed else 429,
    )


def config(capacity: int, rate: float = 1.0, sensitivity: str = "internal") -> RateLimitConfig:
    return RateLimitConfig.model_validate({
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": rate,
                    "capacity": capacity,
                    "algorithm": "token_bucket",
                    "fail_mode": "open",
                    "sensitivity": sensitivity,
                }
            }
        }
    })


def test_replay_policy_reports_newly_denied_and_identifier_impact():
    events = [
        event(timestamp=100.0, identifier="free_user"),
        event(timestamp=100.1, identifier="free_user"),
        event(timestamp=100.2, identifier="free_user"),
        event(timestamp=100.3, identifier="other_user"),
    ]

    report = replay_policy(
        active_config=config(capacity=3),
        proposed_config=config(capacity=1),
        events=events,
    )

    assert report["mode"] == "recent_events_replay"
    assert report["summary"]["events_replayed"] == 4
    assert report["summary"]["newly_denied"] == 2
    assert report["summary"]["newly_allowed"] == 0
    route = report["routes"][0]
    assert route["route"] == "/api/data"
    assert route["events"] == 4
    assert route["newly_denied"] == 2
    identifier = next(item for item in report["identifiers"] if item["identifier"] == "free_user")
    assert identifier["events"] == 3
    assert identifier["newly_denied"] == 2


def test_replay_policy_reports_newly_allowed_when_policy_relaxes():
    events = [
        event(timestamp=100.0, identifier="free_user", allowed=True),
        event(timestamp=100.1, identifier="free_user", allowed=False),
        event(timestamp=100.2, identifier="free_user", allowed=False),
    ]

    report = replay_policy(
        active_config=config(capacity=1),
        proposed_config=config(capacity=3),
        events=events,
    )

    assert report["summary"]["newly_denied"] == 0
    assert report["summary"]["newly_allowed"] == 2
    assert report["routes"][0]["proposed_replay_denied"] == 0


def test_replay_policy_tracks_sensitive_route_impact():
    events = [
        event(timestamp=100.0, allowed=True, sensitivity="sensitive"),
        event(timestamp=100.1, allowed=True, sensitivity="sensitive"),
    ]

    report = replay_policy(
        active_config=config(capacity=2, sensitivity="sensitive"),
        proposed_config=config(capacity=1, sensitivity="sensitive"),
        events=events,
    )

    assert report["summary"]["sensitive_routes_impacted"] == ["/api/data"]

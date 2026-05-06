from app.ai.anomalies import detect_anomalies
from app.ai.telemetry import RateLimitEvent


def event(
    *,
    timestamp: float,
    route_path: str = "/api/data",
    identifier: str = "free_user",
    allowed: bool = True,
    retry_after_s: int | None = None,
    redis_fail_open: bool = False,
    sensitivity: str = "internal",
    fail_mode: str = "open",
) -> RateLimitEvent:
    return RateLimitEvent(
        timestamp=timestamp,
        route_path=route_path,
        identifier=identifier,
        allowed=allowed,
        remaining=1 if allowed else 0,
        capacity=5,
        rate=1.0,
        retry_after_s=retry_after_s,
        redis_fail_open=redis_fail_open,
        algorithm="token_bucket",
        fail_mode=fail_mode,
        tier="free",
        owner="api-platform",
        sensitivity=sensitivity,
        rule_version=1,
        method="GET",
        status_code=200 if allowed else 429,
    )


def finding_types(report):
    return {item["type"] for item in report["findings"]}


def test_anomalies_report_noop_for_normal_low_volume_traffic():
    report = detect_anomalies(
        [event(timestamp=100 + index, identifier=f"user_{index}") for index in range(4)],
        generated_at=123,
    )

    assert report["schema_version"] == 1
    assert report["events_analyzed"] == 4
    assert report["count"] == 0
    assert report["findings"] == []


def test_detects_route_spike_across_many_identifiers():
    report = detect_anomalies(
        [event(timestamp=100 + index, identifier=f"user_{index % 10}") for index in range(55)],
        generated_at=123,
    )

    spike = next(item for item in report["findings"] if item["type"] == "route_traffic_spike")
    assert spike["route"] == "/api/data"
    assert spike["severity"] == "medium"
    assert spike["evidence"]["requests"] == 55
    assert spike["evidence"]["unique_identifiers"] == 10


def test_detects_concentrated_offender_and_retry_loop():
    report = detect_anomalies(
        [
            event(
                timestamp=100 + index * 0.2,
                identifier="abusive_user",
                allowed=False,
                retry_after_s=1,
            )
            for index in range(5)
        ],
        generated_at=123,
    )

    assert {"concentrated_offender", "retry_loop"} <= finding_types(report)
    offender = next(item for item in report["findings"] if item["type"] == "concentrated_offender")
    assert offender["identifier"] == "abusive_user"
    assert offender["evidence"]["denied"] == 5
    retry = next(item for item in report["findings"] if item["type"] == "retry_loop")
    assert retry["evidence"]["fast_retry_gaps"] == [0.2, 0.2, 0.2, 0.2]


def test_detects_sensitive_route_probing_and_redis_outage_exposure():
    report = detect_anomalies(
        [
            event(
                timestamp=100 + index,
                route_path="/api/accounts/{account_id}/data",
                identifier=f"probe_{index}",
                sensitivity="sensitive",
                redis_fail_open=index == 0,
            )
            for index in range(3)
        ],
        generated_at=123,
    )

    assert {"sensitive_route_probing", "redis_outage_exposure"} <= finding_types(report)
    probing = next(item for item in report["findings"] if item["type"] == "sensitive_route_probing")
    assert probing["severity"] == "high"
    assert probing["evidence"]["unique_identifiers"] == 3
    outage = next(item for item in report["findings"] if item["type"] == "redis_outage_exposure")
    assert outage["severity"] == "high"
    assert outage["evidence"]["redis_fail_open"] == 1

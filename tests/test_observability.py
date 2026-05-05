import json
from uuid import uuid4

import pytest
import redis.asyncio as redis

import app.api.depends as depends
from app.ai.telemetry import RateLimitEvent, telemetry_hub
from app.config import settings
from app.core.limiter import RedisRateLimiter
from app.main import app
from app.observability.telemetry_store import SQLiteTelemetryStore
from app.observability.tracing import parse_otlp_headers


class FailingScriptRedis:
    def register_script(self, _script):
        async def fail(*_args, **_kwargs):
            raise redis.ConnectionError("redis unavailable")

        return fail


class FailingPingRedis:
    async def ping(self):
        raise redis.ConnectionError("redis unavailable")


class BrokenTelemetryStore:
    def record(self, _event):
        raise RuntimeError("store unavailable")

    def summary(self):
        raise RuntimeError("store unavailable")

    def recent(self, limit: int = 100):
        raise RuntimeError("store unavailable")


def persisted_event(
    *,
    timestamp: float,
    route_path: str = "/api/data",
    identifier: str = "persisted_user",
    allowed: bool = True,
) -> RateLimitEvent:
    return RateLimitEvent(
        timestamp=timestamp,
        route_path=route_path,
        identifier=identifier,
        allowed=allowed,
        remaining=4 if allowed else 0,
        capacity=5,
        rate=1.0,
        retry_after_s=None if allowed else 1,
        redis_fail_open=False,
    )


@pytest.mark.asyncio
async def test_request_id_header_is_echoed(client):
    response = await client.get("/health", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-id"


@pytest.mark.asyncio
async def test_request_id_header_is_generated(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert "x-trace-id" not in response.headers


@pytest.mark.asyncio
async def test_trace_id_header_is_emitted_when_tracing_enabled(client):
    settings.enable_tracing = True
    settings.trace_console_exporter = False

    response = await client.get("/health")

    assert response.status_code == 200
    assert len(response.headers["x-trace-id"]) == 32


def test_parse_otlp_headers():
    assert parse_otlp_headers(None) is None
    assert parse_otlp_headers("") is None
    assert parse_otlp_headers("authorization=Bearer token,x-tenant=demo") == {
        "authorization": "Bearer token",
        "x-tenant": "demo",
    }
    assert parse_otlp_headers("invalid, x-api-key = secret ") == {
        "x-api-key": "secret",
    }


def test_otlp_http_exporter_dependency_is_available():
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    assert OTLPSpanExporter is not None


@pytest.mark.asyncio
async def test_ready_reports_redis_state(client, redis_client):
    app.state.redis_client = redis_client

    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "redis": "ok"}

    app.state.redis_client = FailingPingRedis()

    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["redis"] == "unavailable"


@pytest.mark.asyncio
async def test_metrics_include_rate_limit_counters(client):
    await client.get("/api/data", headers={"X-API-Key": "metrics_user"})

    for _ in range(6):
        await client.get("/api/data", headers={"X-API-Key": "limited_metrics_user"})

    response = await client.get("/metrics")

    assert response.status_code == 200
    text = response.text
    assert "rate_limiter_allowed_requests_total" in text
    assert "rate_limiter_denied_requests_total" in text
    assert 'route="/api/data"' in text


@pytest.mark.asyncio
async def test_metrics_include_redis_failure_counters(client):
    depends.redis_limiter = RedisRateLimiter(FailingScriptRedis())

    await client.get("/api/data", headers={"X-API-Key": "fail_open_metrics"})
    await client.get("/api/limited-health", headers={"X-API-Key": "fail_closed_metrics"})

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "rate_limiter_redis_fail_open_total" in response.text
    assert "rate_limiter_redis_fail_closed_total" in response.text


@pytest.mark.asyncio
async def test_telemetry_hashes_identifiers_when_enabled(client):
    settings.hash_identifiers = True
    raw_identifier = "secret-user-key"

    for _ in range(6):
        await client.get("/api/data", headers={"X-API-Key": raw_identifier})

    response = await client.get("/ai/signals", headers={"X-Admin-Key": "dev-admin-key"})

    assert response.status_code == 200
    body = json.dumps(response.json())
    assert raw_identifier not in body
    assert "sha256:" in body


@pytest.mark.asyncio
async def test_persistent_telemetry_admin_endpoint(client):
    store = SQLiteTelemetryStore("tmp-test-data/telemetry/events.sqlite3")
    telemetry_hub.set_store(store)

    await client.get("/api/data", headers={"X-API-Key": "persisted_user"})

    response = await client.get(
        "/admin/telemetry/persistent",
        headers={"X-Admin-Key": "dev-admin-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["enabled"] is True
    assert body["summary"]["events"] >= 1
    assert body["analytics"]["routes"][0]["route"] == "/api/data"
    assert body["analytics"]["routes"][0]["requests"] >= 1
    assert body["analytics"]["top_offenders"] == []
    assert body["events"][0]["route_path"] == "/api/data"
    assert body["events"][0]["identifier"] == "persisted_user"


@pytest.mark.asyncio
async def test_persistent_telemetry_admin_endpoint_filters_by_time_range(client):
    store = SQLiteTelemetryStore(f"tmp-test-data/telemetry/{uuid4()}-ranged-events.sqlite3")
    telemetry_hub.set_store(store)
    store.record(persisted_event(timestamp=100, identifier="old_user", allowed=False))
    store.record(persisted_event(timestamp=200, identifier="kept_user", allowed=False))
    store.record(persisted_event(timestamp=300, identifier="future_user"))

    response = await client.get(
        "/admin/telemetry/persistent?since=150&until=250&limit=10",
        headers={"X-Admin-Key": "dev-admin-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filters"] == {"limit": 10, "since": 150.0, "until": 250.0}
    assert body["summary"]["events"] == 1
    assert body["summary"]["denied"] == 1
    assert body["analytics"]["routes"] == [
        {
            "route": "/api/data",
            "requests": 1,
            "denied": 1,
            "denied_pct": 100.0,
            "redis_fail_open": 0,
        }
    ]
    assert body["analytics"]["top_offenders"] == [{"identifier": "kept_user", "denied": 1}]
    assert [event["identifier"] for event in body["events"]] == ["kept_user"]


@pytest.mark.asyncio
async def test_persistent_telemetry_rejects_invalid_time_range(client):
    response = await client.get(
        "/admin/telemetry/persistent?since=250&until=150",
        headers={"X-Admin-Key": "dev-admin-key"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "since must be less than or equal to until"


@pytest.mark.asyncio
async def test_persistent_telemetry_reports_disabled(client):
    response = await client.get(
        "/admin/telemetry/persistent",
        headers={"X-Admin-Key": "dev-admin-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["enabled"] is False
    assert body["analytics"] == {"routes": [], "top_offenders": []}
    assert body["events"] == []


@pytest.mark.asyncio
async def test_persistent_telemetry_failures_do_not_block_requests(client):
    telemetry_hub.set_store(BrokenTelemetryStore())

    response = await client.get("/api/data", headers={"X-API-Key": "broken_store_user"})

    assert response.status_code == 200

    response = await client.get(
        "/admin/telemetry/persistent",
        headers={"X-Admin-Key": "dev-admin-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["enabled"] is True
    assert body["summary"]["status"] == "unavailable"
    assert body["summary"]["persistent_errors"] >= 1
    assert body["analytics"] == {"routes": [], "top_offenders": []}
    assert body["events"] == []

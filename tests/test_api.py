import asyncio
import json
import logging
from pathlib import Path

import pytest
import redis.asyncio as redis

import app.api.depends as depends
from app.config import settings
from app.core.limiter import RedisRateLimiter
from app.core.rules import RulesManager


@pytest.mark.asyncio
async def test_limited_health_check_rate_limit(client):
    headers = {"X-API-Key": "test_key"}
    
    for i in range(10):
        response = await client.get("/api/limited-health", headers=headers)
        assert response.status_code == 200
        assert "x-ratelimit-remaining" in response.headers
        assert int(response.headers["x-ratelimit-remaining"]) == 9 - i
        
    response = await client.get("/api/limited-health", headers=headers)
    assert response.status_code == 429
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert "retry-after" in response.headers


@pytest.mark.asyncio
async def test_platform_health_is_not_rate_limited(client):
    headers = {"X-API-Key": "test_key"}

    for _ in range(12):
        response = await client.get("/health", headers=headers)
        assert response.status_code == 200
        assert "x-ratelimit-remaining" not in response.headers


@pytest.mark.asyncio
async def test_fixed_window_route_rule(client):
    rules_path = "tmp-test-data/fixed-window-api/rules.json"

    Path(rules_path).parent.mkdir(parents=True, exist_ok=True)
    Path(rules_path).write_text(
        json.dumps(
            {
                "routes": {
                    "/api/data": {
                        "global_limit": {
                            "rate": 1.0,
                            "capacity": 2,
                            "algorithm": "fixed_window",
                            "fail_mode": "open",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    depends.rules_manager = RulesManager(rules_path)

    headers = {"X-API-Key": "fixed_window_user"}
    assert (await client.get("/api/data", headers=headers)).status_code == 200
    response = await client.get("/api/data", headers=headers)
    assert response.status_code == 200
    assert response.headers["x-ratelimit-algorithm"] == "fixed_window"

    response = await client.get("/api/data", headers=headers)
    assert response.status_code == 429
    assert response.headers["x-ratelimit-algorithm"] == "fixed_window"
    assert "retry-after" in response.headers


@pytest.mark.asyncio
async def test_sliding_window_route_rule(client):
    rules_path = "tmp-test-data/sliding-window-api/rules.json"

    Path(rules_path).parent.mkdir(parents=True, exist_ok=True)
    Path(rules_path).write_text(
        json.dumps(
            {
                "routes": {
                    "/api/data": {
                        "global_limit": {
                            "rate": 1.0,
                            "capacity": 2,
                            "algorithm": "sliding_window",
                            "fail_mode": "open",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    depends.rules_manager = RulesManager(rules_path)

    headers = {"X-API-Key": "sliding_window_user"}
    assert (await client.get("/api/data", headers=headers)).status_code == 200
    response = await client.get("/api/data", headers=headers)
    assert response.status_code == 200
    assert response.headers["x-ratelimit-algorithm"] == "sliding_window"

    response = await client.get("/api/data", headers=headers)
    assert response.status_code == 429
    assert response.headers["x-ratelimit-algorithm"] == "sliding_window"
    assert "retry-after" in response.headers


@pytest.mark.asyncio
async def test_templated_route_uses_route_pattern_for_limits(client):
    rules_path = "tmp-test-data/templated-route/rules.json"
    Path(rules_path).parent.mkdir(parents=True, exist_ok=True)
    Path(rules_path).write_text(
        json.dumps(
            {
                "routes": {
                    "/api/accounts/{account_id}/data": {
                        "global_limit": {
                            "rate": 0.001,
                            "capacity": 1,
                            "fail_mode": "open",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    depends.rules_manager = RulesManager(rules_path)

    headers = {"X-API-Key": "templated_user"}
    first = await client.get("/api/accounts/acct_1/data", headers=headers)
    second = await client.get("/api/accounts/acct_2/data", headers=headers)

    assert first.status_code == 200
    assert first.json()["account_id"] == "acct_1"
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_rule_metadata_is_included_in_decision_logs(client, caplog):
    rules_path = "tmp-test-data/rule-metadata/rules.json"
    Path(rules_path).parent.mkdir(parents=True, exist_ok=True)
    Path(rules_path).write_text(
        json.dumps(
            {
                "routes": {
                    "/api/accounts/{account_id}/data": {
                        "global_limit": {
                            "rate": 1.0,
                            "capacity": 2,
                            "fail_mode": "open",
                            "tier": "enterprise",
                            "owner": "accounts",
                            "sensitivity": "sensitive",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    depends.rules_manager = RulesManager(rules_path)
    caplog.set_level(logging.INFO, logger="rate_limiter")

    response = await client.get(
        "/api/accounts/acct_metadata/data",
        headers={"X-API-Key": "metadata_user"},
    )

    assert response.status_code == 200
    assert "route=/api/accounts/{account_id}/data" in caplog.text
    assert "tier=enterprise" in caplog.text
    assert "owner=accounts" in caplog.text
    assert "sensitivity=sensitive" in caplog.text


@pytest.mark.asyncio
async def test_forwarded_for_is_ignored_without_trusted_proxy(client):
    rules_path = "tmp-test-data/xff-untrusted/rules.json"
    Path(rules_path).parent.mkdir(parents=True, exist_ok=True)
    Path(rules_path).write_text(
        json.dumps(
            {
                "routes": {
                    "/api/data": {
                        "global_limit": {
                            "rate": 0.001,
                            "capacity": 1,
                            "fail_mode": "open",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    depends.rules_manager = RulesManager(rules_path)

    first = await client.get("/api/data", headers={"X-Forwarded-For": "203.0.113.10"})
    second = await client.get("/api/data", headers={"X-Forwarded-For": "203.0.113.11"})

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_forwarded_for_is_used_for_trusted_proxy(client):
    settings.trusted_proxy_ips = "127.0.0.1"
    rules_path = "tmp-test-data/xff-trusted/rules.json"
    Path(rules_path).parent.mkdir(parents=True, exist_ok=True)
    Path(rules_path).write_text(
        json.dumps(
            {
                "routes": {
                    "/api/data": {
                        "global_limit": {
                            "rate": 0.001,
                            "capacity": 1,
                            "fail_mode": "open",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    depends.rules_manager = RulesManager(rules_path)

    first = await client.get("/api/data", headers={"X-Forwarded-For": "203.0.113.10"})
    second = await client.get("/api/data", headers={"X-Forwarded-For": "203.0.113.11"})
    third = await client.get("/api/data", headers={"X-Forwarded-For": "203.0.113.10"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


@pytest.mark.asyncio
async def test_race_conditions(client):
    async def make_request():
        return await client.get("/api/data", headers={"X-API-Key": "global_user"})
        
    responses = await asyncio.gather(*(make_request() for _ in range(10)))
    
    success_count = sum(1 for r in responses if r.status_code == 200)
    limit_count = sum(1 for r in responses if r.status_code == 429)
    
    assert success_count == 5
    assert limit_count == 5


class FailingRedis:
    def register_script(self, _script):
        async def fail(*_args, **_kwargs):
            raise redis.ConnectionError("redis unavailable")

        return fail


@pytest.mark.asyncio
async def test_fail_open_route_allows_when_redis_unavailable(client):
    depends.redis_limiter = RedisRateLimiter(FailingRedis())

    response = await client.get("/api/data", headers={"X-API-Key": "free_user_key"})

    assert response.status_code == 200
    assert response.headers["x-ratelimit-remaining"] == "4"


@pytest.mark.asyncio
async def test_fail_closed_route_rejects_when_redis_unavailable(client):
    depends.redis_limiter = RedisRateLimiter(FailingRedis())

    response = await client.get("/api/limited-health", headers={"X-API-Key": "test_key"})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"

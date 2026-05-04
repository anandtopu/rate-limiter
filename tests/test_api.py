import asyncio
import json
from pathlib import Path

import pytest
import redis.asyncio as redis

import app.api.depends as depends
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

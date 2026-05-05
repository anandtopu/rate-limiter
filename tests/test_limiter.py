"""
Unit tests for the Redis Rate Limiter algorithms.
"""
import asyncio

import pytest
import redis.asyncio as redis
from pydantic import ValidationError

from app.core.limiter import RedisRateLimiter
from app.models.rules import RateLimitRule


@pytest.mark.asyncio
async def test_token_bucket(redis_client):
    """
    Test the token bucket algorithm mechanics: consuming tokens,
    exhausting the bucket, rejecting, and refilling after a delay.
    """
    limiter = RedisRateLimiter(redis_client)
    key = "test_bucket"
    rate = 10.0
    capacity = 5

    result = await limiter.is_allowed(key, rate, capacity)
    assert result.allowed is True
    assert result.redis_fail_open is False
    assert result.remaining == 4

    for _ in range(4):
        result = await limiter.is_allowed(key, rate, capacity)
        assert result.allowed is True
        assert result.redis_fail_open is False

    assert result.remaining < 1

    result = await limiter.is_allowed(key, rate, capacity)
    assert result.allowed is False
    assert result.redis_fail_open is False
    assert result.remaining < 1
    assert result.retry_after_s == 1

    await asyncio.sleep(0.15)
    result = await limiter.is_allowed(key, rate, capacity)
    assert result.allowed is True
    assert result.redis_fail_open is False


@pytest.mark.asyncio
async def test_retry_after_uses_time_until_next_token(redis_client):
    limiter = RedisRateLimiter(redis_client)
    key = "retry_after_bucket"

    for _ in range(5):
        result = await limiter.is_allowed(key, rate=1.0, capacity=5)
        assert result.allowed is True

    result = await limiter.is_allowed(key, rate=1.0, capacity=5)
    assert result.allowed is False
    assert result.retry_after_s == 1


def test_rule_values_must_be_positive():
    with pytest.raises(ValidationError):
        RateLimitRule(rate=0, capacity=1)

    with pytest.raises(ValidationError):
        RateLimitRule(rate=1, capacity=0)


def test_rule_fail_mode_must_be_known():
    with pytest.raises(ValidationError):
        RateLimitRule(rate=1, capacity=1, fail_mode="maybe")


def test_rule_algorithm_must_be_known():
    with pytest.raises(ValidationError):
        RateLimitRule(rate=1, capacity=1, algorithm="leaky_bucket")


def test_rule_sensitivity_must_be_known_when_set():
    rule = RateLimitRule(
        rate=1,
        capacity=1,
        owner="api-platform",
        sensitivity="sensitive",
    )
    assert rule.owner == "api-platform"
    assert rule.sensitivity == "sensitive"

    with pytest.raises(ValidationError):
        RateLimitRule(rate=1, capacity=1, sensitivity="secret")


@pytest.mark.asyncio
async def test_fixed_window_algorithm(redis_client):
    limiter = RedisRateLimiter(redis_client)
    key = "fixed_window_bucket"

    for _ in range(3):
        result = await limiter.is_allowed(
            key,
            rate=1.0,
            capacity=3,
            algorithm="fixed_window",
        )
        assert result.allowed is True

    result = await limiter.is_allowed(
        key,
        rate=1.0,
        capacity=3,
        algorithm="fixed_window",
    )

    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after_s >= 1


class FailingRedis:
    def register_script(self, _script):
        async def fail(*_args, **_kwargs):
            raise redis.ConnectionError("redis unavailable")

        return fail


@pytest.mark.asyncio
async def test_redis_fail_open_allows_request():
    limiter = RedisRateLimiter(FailingRedis())

    result = await limiter.is_allowed("fail_open", rate=1.0, capacity=5, fail_mode="open")

    assert result.allowed is True
    assert result.redis_failed is True
    assert result.redis_fail_open is True


@pytest.mark.asyncio
async def test_redis_fail_closed_rejects_request():
    limiter = RedisRateLimiter(FailingRedis())

    result = await limiter.is_allowed("fail_closed", rate=1.0, capacity=5, fail_mode="closed")

    assert result.allowed is False
    assert result.retry_after_s == 1
    assert result.redis_failed is True
    assert result.redis_fail_open is False

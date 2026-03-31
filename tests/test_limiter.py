"""
Unit tests for the Redis Rate Limiter algorithms.
"""
import asyncio
import pytest

from app.core.limiter import RedisRateLimiter


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

    allowed, remaining, redis_fail_open = await limiter.is_allowed(key, rate, capacity)
    assert allowed is True
    assert redis_fail_open is False
    assert remaining == 4

    for _ in range(4):
        allowed, remaining, redis_fail_open = await limiter.is_allowed(key, rate, capacity)
        assert allowed is True
        assert redis_fail_open is False

    assert remaining == 0

    allowed, remaining, redis_fail_open = await limiter.is_allowed(key, rate, capacity)
    assert allowed is False
    assert redis_fail_open is False
    assert remaining == 0

    await asyncio.sleep(0.15)
    allowed, remaining, redis_fail_open = await limiter.is_allowed(key, rate, capacity)
    assert allowed is True
    assert redis_fail_open is False

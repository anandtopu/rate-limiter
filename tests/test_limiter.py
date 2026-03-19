import pytest
from app.core.limiter import RedisRateLimiter
import asyncio

@pytest.mark.asyncio
async def test_token_bucket(redis_client):
    limiter = RedisRateLimiter(redis_client)
    key = "test_bucket"
    rate = 10.0
    capacity = 5
    
    allowed, remaining = await limiter.is_allowed(key, rate, capacity)
    assert allowed is True
    assert remaining == 4
    
    for _ in range(4):
        allowed, remaining = await limiter.is_allowed(key, rate, capacity)
        assert allowed is True
    
    assert remaining == 0
    
    allowed, remaining = await limiter.is_allowed(key, rate, capacity)
    assert allowed is False
    assert remaining == 0
    
    await asyncio.sleep(0.15)
    allowed, remaining = await limiter.is_allowed(key, rate, capacity)
    assert allowed is True

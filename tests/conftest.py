import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
import redis.asyncio as redis
from app.core.limiter import RedisRateLimiter
import app.api.depends as depends
from app.core.rules import RulesManager

from fakeredis import FakeAsyncRedis

@pytest_asyncio.fixture()
async def redis_client():
    client = FakeAsyncRedis()
    await client.flushdb()
    yield client
    await client.aclose()

@pytest_asyncio.fixture()
async def client(redis_client):
    depends.redis_limiter = RedisRateLimiter(redis_client)
    depends.rules_manager = RulesManager("rules.json")
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

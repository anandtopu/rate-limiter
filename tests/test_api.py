import pytest
import asyncio

@pytest.mark.asyncio
async def test_health_check_rate_limit(client):
    headers = {"X-API-Key": "test_key"}
    
    for i in range(10):
        response = await client.get("/health", headers=headers)
        assert response.status_code == 200
        assert "x-ratelimit-remaining" in response.headers
        assert int(response.headers["x-ratelimit-remaining"]) == 9 - i
        
    response = await client.get("/health", headers=headers)
    assert response.status_code == 429
    assert response.headers["x-ratelimit-remaining"] == "0"
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

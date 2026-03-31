import pytest


@pytest.mark.asyncio
async def test_ai_signals_and_recommendations(client):
    headers = {"X-API-Key": "ai_test_key"}

    for _ in range(3):
        r = await client.get("/health", headers=headers)
        assert r.status_code == 200

    r = await client.get("/ai/signals")
    assert r.status_code == 200
    data = r.json()
    assert "routes" in data
    assert "events_in_window" in data
    assert data["events_in_window"] >= 3

    r = await client.post("/ai/recommendations")
    assert r.status_code == 200
    rec = r.json()
    assert "generated_at" in rec
    assert "items" in rec

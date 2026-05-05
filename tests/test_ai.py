import pytest


@pytest.mark.asyncio
async def test_ai_signals_and_recommendations(client):
    headers = {"X-API-Key": "ai_test_key"}
    admin_headers = {"X-Admin-Key": "dev-admin-key"}

    for _ in range(3):
        r = await client.get("/api/limited-health", headers=headers)
        assert r.status_code == 200

    r = await client.get("/ai/signals", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert "routes" in data
    assert "events_in_window" in data
    assert data["events_in_window"] >= 3

    r = await client.post("/ai/recommendations", headers=admin_headers)
    assert r.status_code == 200
    rec = r.json()
    assert "generated_at" in rec
    assert "items" in rec

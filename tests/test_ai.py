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


@pytest.mark.asyncio
async def test_ai_signals_use_route_templates_for_path_parameters(client):
    admin_headers = {"X-Admin-Key": "dev-admin-key"}

    response = await client.get(
        "/api/accounts/acct_telemetry/data",
        headers={"X-API-Key": "templated_signal_user"},
    )
    assert response.status_code == 200

    response = await client.get("/ai/signals", headers=admin_headers)
    assert response.status_code == 200
    routes = {item["route"] for item in response.json()["routes"]}
    assert "/api/accounts/{account_id}/data" in routes
    assert "/api/accounts/acct_telemetry/data" not in routes

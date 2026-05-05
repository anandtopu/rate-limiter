import pytest
import redis.asyncio as redis

import app.api.depends as depends
from app.core.limiter import RedisRateLimiter


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
    assert "anomalies" in data
    assert data["anomalies"]["schema_version"] == 1

    r = await client.post("/ai/recommendations", headers=admin_headers)
    assert r.status_code == 200
    rec = r.json()
    assert "generated_at" in rec
    assert rec["schema_version"] == 2
    assert "feature_summary" in rec
    assert "items" in rec


@pytest.mark.asyncio
async def test_admin_ai_anomalies_endpoint_reports_findings(client):
    admin_headers = {"X-Admin-Key": "dev-admin-key"}

    for _ in range(10):
        await client.get("/api/data", headers={"X-API-Key": "anomaly_abuse_user"})

    response = await client.get("/admin/ai/anomalies", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["events_analyzed"] >= 6
    finding_types = {item["type"] for item in body["findings"]}
    assert "concentrated_offender" in finding_types


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


@pytest.mark.asyncio
async def test_recommendation_draft_turns_tuning_recommendation_into_dry_run_policy(client):
    admin_headers = {"X-Admin-Key": "dev-admin-key"}
    headers = {"X-API-Key": "recommendation_draft_user"}

    for _ in range(25):
        await client.get("/api/data", headers=headers)

    response = await client.post("/admin/rules/recommendation-draft", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    tuning_change = next(change for change in body["changes"] if change["type"] == "tuning")
    assert tuning_change["route"] == "/api/data"
    assert tuning_change["after"]["capacity"] > tuning_change["before"]["capacity"]
    assert tuning_change["after"]["rate"] > tuning_change["before"]["rate"]
    assert body["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == tuning_change[
        "after"
    ]["capacity"]
    tuning_recommendation = next(
        item for item in body["recommendations"]["items"] if item["type"] == "tuning"
    )
    assert tuning_recommendation["id"] == "rec_tuning_api_data"
    assert tuning_recommendation["proposed_change"]["kind"] == "scale_route_limit"
    assert tuning_recommendation["confidence"] > 0
    assert body["dry_run"]["valid"] is True
    assert body["dry_run"]["applied"] is False


class FailingRedis:
    def register_script(self, _script):
        async def fail(*_args, **_kwargs):
            raise redis.ConnectionError("redis unavailable")

        return fail


@pytest.mark.asyncio
async def test_recommendation_draft_turns_fail_open_into_fail_closed_policy(client):
    admin_headers = {"X-Admin-Key": "dev-admin-key"}
    depends.redis_limiter = RedisRateLimiter(FailingRedis())

    response = await client.get(
        "/api/accounts/acct_outage/data",
        headers={"X-API-Key": "recommendation_fail_open_user"},
    )
    assert response.status_code == 200

    response = await client.post("/admin/rules/recommendation-draft", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    reliability_change = next(
        change for change in body["changes"] if change["type"] == "reliability"
    )
    assert reliability_change["route"] == "/api/accounts/{account_id}/data"
    assert reliability_change["before"]["fail_mode"] == "open"
    assert reliability_change["after"]["fail_mode"] == "closed"
    reliability_recommendation = next(
        item for item in body["recommendations"]["items"] if item["type"] == "reliability"
    )
    assert reliability_recommendation["proposed_change"]["kind"] == "set_fail_mode"
    assert reliability_recommendation["safety_notes"]
    assert body["rules"]["routes"]["/api/accounts/{account_id}/data"]["global_limit"][
        "fail_mode"
    ] == "closed"


@pytest.mark.asyncio
async def test_draft_from_recommendations_consumes_algorithm_and_abuse_proposals(client):
    recommendations = {
        "generated_at": 123,
        "schema_version": 2,
        "items": [
            {
                "type": "algorithm",
                "route": "/api/limited-health",
                "rationale": "Use sliding window for broad fixed-window pressure.",
                "proposed_change": {
                    "kind": "set_algorithm",
                    "route": "/api/limited-health",
                    "algorithm": "sliding_window",
                },
            },
            {
                "type": "abuse",
                "route": "/api/data",
                "rationale": "Known client is repeatedly denied.",
                "signal": {"identifier": "abusive_user"},
                "proposed_change": {
                    "kind": "add_identifier_override",
                    "route": "/api/data",
                    "identifier": "abusive_user",
                    "rate_multiplier": 0.5,
                    "capacity_multiplier": 0.5,
                },
            },
        ],
    }

    draft = depends.rules_manager.draft_from_recommendations(recommendations)

    assert draft["rules"]["routes"]["/api/limited-health"]["global_limit"][
        "algorithm"
    ] == "sliding_window"
    override = draft["rules"]["routes"]["/api/data"]["overrides"]["abusive_user"]
    assert override["capacity"] == 3
    assert override["rate"] == 0.5
    assert [change["type"] for change in draft["changes"]] == ["algorithm", "abuse"]

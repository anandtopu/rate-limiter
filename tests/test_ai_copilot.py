import json
from pathlib import Path
from uuid import uuid4

import pytest

import app.api.depends as depends
from app.config import settings
from app.core.rules import RulesManager

ADMIN_HEADERS = {"X-Admin-Key": "dev-admin-key"}
RUNTIME_DIR = Path("tmp-test-data")


def runtime_rules_path():
    path = RUNTIME_DIR / str(uuid4()) / "rules.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_rules(path, *, capacity=5, rate=1.0):
    path.write_text(
        json.dumps({
            "routes": {
                "/api/data": {
                    "global_limit": {
                        "rate": rate,
                        "capacity": capacity,
                        "fail_mode": "open",
                        "sensitivity": "internal",
                    }
                }
            }
        }),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_policy_copilot_is_disabled_by_default(client):
    response = await client.post(
        "/admin/ai/policy-copilot",
        headers=ADMIN_HEADERS,
        json={"prompt": "Explain current limiter pressure."},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "AI policy copilot is disabled"


@pytest.mark.asyncio
async def test_policy_copilot_fake_provider_explains_without_policy_json(client):
    settings.ai_copilot_enabled = True

    response = await client.post(
        "/admin/ai/policy-copilot",
        headers=ADMIN_HEADERS,
        json={"prompt": "Explain current limiter pressure."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["provider"] == "fake"
    assert body["applied"] is False
    assert "Fake copilot analyzed" in body["explanation"]
    assert body["proposed_rules"] is None
    assert body["validation"]["status"] == "skipped"
    assert body["dry_run"] is None
    assert body["safety_constraints"]


@pytest.mark.asyncio
async def test_policy_copilot_validates_and_dry_runs_generated_rules_without_applying(client):
    settings.ai_copilot_enabled = True
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5, rate=1)
    depends.rules_manager = RulesManager(str(rules_path))

    for _ in range(4):
        await client.get("/api/data", headers={"X-API-Key": "copilot_dry_run_user"})

    proposed_rules = {
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": 0.001,
                    "capacity": 1,
                    "fail_mode": "open",
                    "sensitivity": "internal",
                }
            }
        }
    }

    response = await client.post(
        "/admin/ai/policy-copilot",
        headers=ADMIN_HEADERS,
        json={
            "prompt": "Validate this generated policy and show the impact.",
            "proposed_rules": proposed_rules,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["validation"]["valid"] is True
    assert body["validation"]["status"] == "valid"
    assert body["validation"]["sensitive_routes"] == []
    assert body["dry_run"]["valid"] is True
    assert body["dry_run"]["applied"] is False
    assert body["dry_run"]["replay"]["summary"]["newly_denied"] > 0
    assert body["proposed_rules"] == proposed_rules

    snapshot = depends.rules_manager.snapshot()
    assert snapshot["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 5
    assert snapshot["version"] == 1


@pytest.mark.asyncio
async def test_policy_copilot_reports_invalid_generated_rules_safely(client):
    settings.ai_copilot_enabled = True
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5, rate=1)
    depends.rules_manager = RulesManager(str(rules_path))

    response = await client.post(
        "/admin/ai/policy-copilot",
        headers=ADMIN_HEADERS,
        json={
            "prompt": "Validate this generated policy.",
            "proposed_rules": {
                "routes": {
                    "/api/data": {
                        "global_limit": {
                            "rate": 0,
                            "capacity": 1,
                            "fail_mode": "open",
                        }
                    }
                }
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert body["validation"]["valid"] is False
    assert body["validation"]["status"] == "invalid"
    assert body["validation"]["errors"]
    assert body["dry_run"] is None
    assert depends.rules_manager.snapshot()["rules"]["routes"]["/api/data"]["global_limit"][
        "capacity"
    ] == 5


@pytest.mark.asyncio
async def test_policy_copilot_rejects_unconfigured_provider(client):
    settings.ai_copilot_enabled = True
    settings.ai_copilot_provider = "openai"

    response = await client.post(
        "/admin/ai/policy-copilot",
        headers=ADMIN_HEADERS,
        json={"prompt": "Explain current limiter pressure."},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "AI policy copilot provider is not configured: openai"

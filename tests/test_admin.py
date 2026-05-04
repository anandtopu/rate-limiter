import json
from pathlib import Path
from uuid import uuid4

import pytest

import app.api.depends as depends
from app.core.rules import RulesManager

ADMIN_HEADERS = {"X-Admin-Key": "dev-admin-key"}
RUNTIME_DIR = Path("tmp-test-data")


def runtime_rules_path():
    path = RUNTIME_DIR / str(uuid4()) / "rules.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_rules(path, capacity=5, rate=0.001):
    path.write_text(
        json.dumps(
            {
                "routes": {
                    "/api/data": {
                        "global_limit": {
                            "rate": rate,
                            "capacity": capacity,
                            "fail_mode": "open",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_admin_auth_required(client):
    response = await client.get("/admin/rules")
    assert response.status_code == 401

    response = await client.get("/admin/rules", headers={"X-Admin-Key": "wrong"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ai_endpoints_require_admin_key(client):
    response = await client.get("/ai/signals")
    assert response.status_code == 401

    response = await client.post("/ai/recommendations", headers=ADMIN_HEADERS)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rule_validation_success_and_failure(client):
    valid_payload = {
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": 2.0,
                    "capacity": 3,
                    "fail_mode": "closed",
                }
            }
        }
    }

    response = await client.post(
        "/admin/rules/validate",
        headers=ADMIN_HEADERS,
        json=valid_payload,
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True

    invalid_payload = {
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": 0,
                    "capacity": 3,
                }
            }
        }
    }

    response = await client.post(
        "/admin/rules/validate",
        headers=ADMIN_HEADERS,
        json=invalid_payload,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rule_dry_run_reports_estimated_impact_without_applying(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5, rate=1)
    depends.rules_manager = RulesManager(str(rules_path))

    for index in range(6):
        response = await client.get("/api/data", headers={"X-API-Key": f"dry_run_{index}"})
        assert response.status_code == 200

    proposed_payload = {
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": 0.001,
                    "capacity": 1,
                    "fail_mode": "closed",
                }
            }
        }
    }

    response = await client.post(
        "/admin/rules/dry-run",
        headers=ADMIN_HEADERS,
        json=proposed_payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["applied"] is False
    assert body["events_analyzed"] >= 6
    assert body["summary"]["estimated_additional_denials"] > 0
    route_report = next(item for item in body["routes"] if item["route"] == "/api/data")
    assert route_report["capacity_delta"] == -4
    assert route_report["fail_mode_changed"] is True

    snapshot = depends.rules_manager.snapshot()
    assert snapshot["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 5
    assert snapshot["version"] == 1


@pytest.mark.asyncio
async def test_rule_dry_run_rejects_invalid_payload(client):
    response = await client.post(
        "/admin/rules/dry-run",
        headers=ADMIN_HEADERS,
        json={"routes": {"/api/data": {"global_limit": {"rate": 0, "capacity": 1}}}},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rule_update_changes_limit_behavior(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))

    update_payload = {
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": 0.001,
                    "capacity": 1,
                    "fail_mode": "open",
                }
            }
        }
    }

    response = await client.put(
        "/admin/rules",
        headers=ADMIN_HEADERS,
        json=update_payload,
    )
    assert response.status_code == 200
    assert response.json()["updated"] is True
    assert response.json()["version"] == 2

    headers = {"X-API-Key": "rule_update_user"}
    response = await client.get("/api/data", headers=headers)
    assert response.status_code == 200

    response = await client.get("/api/data", headers=headers)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_failed_rule_update_preserves_active_rules(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=2)
    depends.rules_manager = RulesManager(str(rules_path))

    invalid_payload = {
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": 0,
                    "capacity": 1,
                }
            }
        }
    }

    response = await client.put(
        "/admin/rules",
        headers=ADMIN_HEADERS,
        json=invalid_payload,
    )
    assert response.status_code == 422

    headers = {"X-API-Key": "preserve_user"}
    assert (await client.get("/api/data", headers=headers)).status_code == 200
    assert (await client.get("/api/data", headers=headers)).status_code == 200
    assert (await client.get("/api/data", headers=headers)).status_code == 429


@pytest.mark.asyncio
async def test_rule_reload_refreshes_from_disk(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=1)
    depends.rules_manager = RulesManager(str(rules_path))

    write_rules(rules_path, capacity=3)

    response = await client.post(
        "/admin/rules/reload",
        headers={
            **ADMIN_HEADERS,
            "X-Audit-Actor": "release-bot",
            "X-Audit-Source": "ops-runbook",
            "X-Audit-Reason": "sync disk-edited rule file",
        },
    )
    assert response.status_code == 200
    assert response.json()["reloaded"] is True
    assert response.json()["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 3

    history = (await client.get("/admin/rules/history", headers=ADMIN_HEADERS)).json()
    reload_entry = history["versions"][-1]
    assert reload_entry["action"] == "reload"
    assert reload_entry["audit"]["actor"] == "release-bot"
    assert reload_entry["audit"]["source"] == "ops-runbook"
    assert reload_entry["audit"]["reason"] == "sync disk-edited rule file"


@pytest.mark.asyncio
async def test_failed_rule_reload_preserves_active_rules(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=2)
    depends.rules_manager = RulesManager(str(rules_path))

    rules_path.write_text("{not json", encoding="utf-8")

    response = await client.post("/admin/rules/reload", headers=ADMIN_HEADERS)
    assert response.status_code == 422

    snapshot = depends.rules_manager.snapshot()
    assert snapshot["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 2


@pytest.mark.asyncio
async def test_rule_history_and_rollback(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=2)
    depends.rules_manager = RulesManager(str(rules_path))

    update_payload = {
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": 0.001,
                    "capacity": 1,
                    "fail_mode": "open",
                }
            }
        }
    }
    update_response = await client.put(
        "/admin/rules",
        headers={
            **ADMIN_HEADERS,
            "X-Audit-Actor": "alice@example.com",
            "X-Audit-Source": "demo-dashboard",
            "X-Audit-Reason": "tighten demo burst capacity",
            "X-Request-ID": "audit-update-request",
        },
        json=update_payload,
    )
    assert update_response.status_code == 200
    assert update_response.json()["version"] == 2

    history_response = await client.get("/admin/rules/history", headers=ADMIN_HEADERS)
    assert history_response.status_code == 200
    history = history_response.json()
    assert history["current_version"] == 2
    assert [item["action"] for item in history["versions"]] == ["initial", "update"]
    initial_audit = history["versions"][0]["audit"]
    assert initial_audit["actor"] == "system"
    assert initial_audit["source"] == "rules-manager:initial"
    update_audit = history["versions"][1]["audit"]
    assert update_audit["actor"] == "alice@example.com"
    assert update_audit["source"] == "demo-dashboard"
    assert update_audit["reason"] == "tighten demo burst capacity"
    assert update_audit["request_id"] == "audit-update-request"

    rollback_response = await client.post(
        "/admin/rules/rollback/1",
        headers={
            **ADMIN_HEADERS,
            "X-Audit-Actor": "bob@example.com",
            "X-Audit-Source": "rollback-cli",
            "X-Audit-Reason": "restore previous free tier limits",
            "X-Request-ID": "audit-rollback-request",
        },
    )
    assert rollback_response.status_code == 200
    assert rollback_response.json()["rolled_back"] is True
    assert rollback_response.json()["rolled_back_from"] == 1
    assert rollback_response.json()["version"] == 3
    assert rollback_response.json()["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 2

    history = (await client.get("/admin/rules/history", headers=ADMIN_HEADERS)).json()
    rollback_audit = history["versions"][2]["audit"]
    assert rollback_audit["actor"] == "bob@example.com"
    assert rollback_audit["source"] == "rollback-cli"
    assert rollback_audit["reason"] == "restore previous free tier limits"
    assert rollback_audit["request_id"] == "audit-rollback-request"


@pytest.mark.asyncio
async def test_rule_rollback_rejects_unknown_version(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=2)
    depends.rules_manager = RulesManager(str(rules_path))

    response = await client.post("/admin/rules/rollback/999", headers=ADMIN_HEADERS)

    assert response.status_code == 422

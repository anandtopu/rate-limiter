import json
from pathlib import Path
from uuid import uuid4

import pytest

import app.api.depends as depends
from app.config import settings
from app.core.rules import RulesManager, SQLiteRuleStore

ADMIN_HEADERS = {"X-Admin-Key": "dev-admin-key"}
RUNTIME_DIR = Path("tmp-test-data")


def runtime_rules_path():
    path = RUNTIME_DIR / str(uuid4()) / "rules.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def runtime_rules_db_path(rules_path):
    return rules_path.parent / "rules.sqlite3"


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


def write_sensitive_rules(path, capacity=5, rate=0.001):
    path.write_text(
        json.dumps(
            {
                "routes": {
                    "/api/accounts/{account_id}/data": {
                        "global_limit": {
                            "rate": rate,
                            "capacity": capacity,
                            "fail_mode": "open",
                            "sensitivity": "sensitive",
                            "owner": "accounts",
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
async def test_named_admin_keys_are_accepted(client):
    settings.admin_api_keys = "primary:primary-key,backup:backup-key"

    response = await client.get("/admin/rules", headers={"X-Admin-Key": "backup-key"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_legacy_admin_key_still_works_when_named_keys_are_configured(client):
    settings.admin_api_keys = "primary:primary-key,backup:backup-key"

    response = await client.get("/admin/rules", headers=ADMIN_HEADERS)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_keys_endpoint_lists_names_without_secrets(client):
    settings.admin_api_keys = "primary:primary-key,backup:backup-key"

    response = await client.get("/admin/keys", headers={"X-Admin-Key": "backup-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "active_key": "backup",
        "configured_keys": ["backup", "default", "primary"],
    }
    assert "backup-key" not in response.text
    assert "primary-key" not in response.text
    assert "dev-admin-key" not in response.text


@pytest.mark.asyncio
async def test_openapi_includes_admin_examples(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]

    rule_examples = paths["/admin/rules"]["put"]["requestBody"]["content"][
        "application/json"
    ]["examples"]
    assert "metadata_policy" in rule_examples
    metadata_rule = rule_examples["metadata_policy"]["value"]["routes"]["/api/data"][
        "global_limit"
    ]
    assert metadata_rule["owner"] == "api-platform"
    assert metadata_rule["sensitivity"] == "public"

    dry_run = paths["/admin/rules/dry-run"]["post"]
    assert "sensitive_policy" in dry_run["requestBody"]["content"]["application/json"][
        "examples"
    ]
    dry_run_examples = dry_run["responses"]["200"]["content"]["application/json"]["examples"]
    assert dry_run_examples["sensitive_tightening"]["value"]["applied"] is False

    import_examples = paths["/admin/rules/import"]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]
    assert import_examples["export_envelope"]["value"]["kind"] == "rate-limiter.rules.export"
    copilot_examples = paths["/admin/ai/policy-copilot"]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]
    assert "explain_only" in copilot_examples
    assert "validate_draft" in copilot_examples
    report_examples = paths["/admin/ai/research-report"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["examples"]
    assert report_examples["generated_report"]["value"]["content_type"] == "text/markdown"

    telemetry_params = {
        parameter["name"]: parameter
        for parameter in paths["/admin/telemetry/persistent"]["get"]["parameters"]
    }
    assert telemetry_params["limit"]["examples"]["recent_50"]["value"] == 50
    assert telemetry_params["since"]["examples"]["demo_start"]["value"] == 1_734_000_000.0

    rollback_params = paths["/admin/rules/rollback/{version}"]["post"]["parameters"]
    version_param = next(
        parameter for parameter in rollback_params if parameter["name"] == "version"
    )
    assert version_param["examples"]["initial"]["value"] == 1
    rollback_examples = paths["/admin/rules/rollback/{version}"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["examples"]
    assert rollback_examples["restore_initial"]["value"]["rolled_back_from"] == 1


@pytest.mark.asyncio
async def test_named_admin_key_is_default_audit_actor(client):
    settings.admin_api_keys = "release-bot:release-key"
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=1)
    depends.rules_manager = RulesManager(str(rules_path))

    response = await client.post(
        "/admin/rules/reload",
        headers={"X-Admin-Key": "release-key"},
    )

    assert response.status_code == 200
    history = (await client.get("/admin/rules/history", headers=ADMIN_HEADERS)).json()
    assert history["versions"][-1]["action"] == "reload"
    assert history["versions"][-1]["audit"]["actor"] == "release-bot"


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
                    "owner": "api-platform",
                    "sensitivity": "internal",
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
    body = response.json()
    assert body["valid"] is True
    assert body["rules"]["routes"]["/api/data"]["global_limit"]["owner"] == "api-platform"
    assert body["rules"]["routes"]["/api/data"]["global_limit"]["sensitivity"] == "internal"

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

    invalid_metadata_payload = {
        "routes": {
            "/api/data": {
                "global_limit": {
                    "rate": 1,
                    "capacity": 3,
                    "sensitivity": "secret",
                }
            }
        }
    }

    response = await client.post(
        "/admin/rules/validate",
        headers=ADMIN_HEADERS,
        json=invalid_metadata_payload,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rule_dry_run_reports_estimated_impact_without_applying(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5, rate=1)
    depends.rules_manager = RulesManager(str(rules_path))

    for _ in range(4):
        response = await client.get("/api/data", headers={"X-API-Key": "dry_run_replay_user"})
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
    assert body["events_analyzed"] >= 4
    assert body["summary"]["estimated_additional_denials"] > 0
    route_report = next(item for item in body["routes"] if item["route"] == "/api/data")
    assert route_report["capacity_delta"] == -4
    assert route_report["fail_mode_changed"] is True
    assert body["replay"]["mode"] == "recent_events_replay"
    assert body["replay"]["summary"]["events_replayed"] >= 4
    assert body["replay"]["summary"]["newly_denied"] > 0
    replay_route = next(item for item in body["replay"]["routes"] if item["route"] == "/api/data")
    assert replay_route["newly_denied"] > 0
    assert body["replay"]["identifiers"]

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
async def test_rule_export_returns_portable_envelope(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))

    response = await client.get("/admin/rules/export", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "rate-limiter.rules.export"
    assert body["schema_version"] == 1
    assert body["version"] == 1
    assert body["store"] == "json"
    assert isinstance(body["exported_at"], int)
    assert body["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 5


@pytest.mark.asyncio
async def test_rule_import_restores_exported_policy_and_records_history(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))
    exported = (await client.get("/admin/rules/export", headers=ADMIN_HEADERS)).json()

    await client.put(
        "/admin/rules",
        headers=ADMIN_HEADERS,
        json={
            "routes": {
                "/api/data": {
                    "global_limit": {
                        "rate": 0.001,
                        "capacity": 1,
                        "fail_mode": "open",
                    }
                }
            }
        },
    )

    response = await client.post(
        "/admin/rules/import",
        headers={
            **ADMIN_HEADERS,
            "X-Audit-Actor": "demo-restore",
            "X-Audit-Reason": "restore exported demo policy",
        },
        json=exported,
    )

    assert response.status_code == 200
    assert response.json()["imported"] is True
    assert response.json()["version"] == 3
    assert response.json()["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 5

    history = (await client.get("/admin/rules/history", headers=ADMIN_HEADERS)).json()
    assert [entry["action"] for entry in history["versions"]] == [
        "initial",
        "update",
        "import",
    ]
    import_entry = history["versions"][-1]
    assert import_entry["audit"]["actor"] == "demo-restore"
    assert import_entry["audit"]["reason"] == "restore exported demo policy"


@pytest.mark.asyncio
async def test_rule_import_accepts_raw_rule_payload(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))

    response = await client.post(
        "/admin/rules/import",
        headers=ADMIN_HEADERS,
        json={
            "routes": {
                "/api/data": {
                    "global_limit": {
                        "rate": 0.001,
                        "capacity": 2,
                        "fail_mode": "open",
                    }
                }
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["imported"] is True
    assert response.json()["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 2


@pytest.mark.asyncio
async def test_rule_import_queues_sensitive_policy_for_approval(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))

    response = await client.post(
        "/admin/rules/import",
        headers={**ADMIN_HEADERS, "X-Audit-Actor": "demo-importer"},
        json={
            "kind": "rate-limiter.rules.export",
            "schema_version": 1,
            "rules": {
                "routes": {
                    "/api/accounts/{account_id}/data": {
                        "global_limit": {
                            "rate": 0.001,
                            "capacity": 1,
                            "fail_mode": "closed",
                            "sensitivity": "sensitive",
                        }
                    }
                }
            },
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["imported"] is False
    assert body["pending_approval"] is True
    assert body["sensitive_routes"] == ["/api/accounts/{account_id}/data"]
    assert body["version"] == 1
    assert "/api/accounts/{account_id}/data" not in depends.rules_manager.snapshot()["rules"][
        "routes"
    ]

    pending = (await client.get("/admin/rules/pending", headers=ADMIN_HEADERS)).json()
    assert pending["requests"][0]["audit"]["actor"] == "demo-importer"


@pytest.mark.asyncio
async def test_rule_import_rejects_invalid_payload_without_applying(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=2)
    depends.rules_manager = RulesManager(str(rules_path))

    response = await client.post(
        "/admin/rules/import",
        headers=ADMIN_HEADERS,
        json={
            "rules": {
                "routes": {
                    "/api/data": {
                        "global_limit": {
                            "rate": 0,
                            "capacity": 1,
                        }
                    }
                }
            }
        },
    )

    assert response.status_code == 422
    snapshot = depends.rules_manager.snapshot()
    assert snapshot["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 2
    assert snapshot["version"] == 1


@pytest.mark.asyncio
async def test_sqlite_rule_store_persists_updates_without_rewriting_seed_json(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5)
    original_seed = json.loads(rules_path.read_text(encoding="utf-8"))
    db_path = runtime_rules_db_path(rules_path)
    depends.rules_manager = RulesManager(
        str(rules_path),
        store=SQLiteRuleStore(str(db_path), seed_config_path=str(rules_path)),
    )

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
    assert response.json()["store"] == "sqlite"
    assert response.json()["version"] == 2
    assert json.loads(rules_path.read_text(encoding="utf-8")) == original_seed

    restarted_manager = RulesManager(
        str(rules_path),
        store=SQLiteRuleStore(str(db_path), seed_config_path=str(rules_path)),
    )
    snapshot = restarted_manager.snapshot()
    assert snapshot["store"] == "sqlite"
    assert snapshot["version"] == 2
    assert snapshot["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 1
    assert [entry["action"] for entry in restarted_manager.history()["versions"]] == [
        "initial",
        "update",
    ]


@pytest.mark.asyncio
async def test_sqlite_rule_store_persists_pending_sensitive_updates(client):
    rules_path = runtime_rules_path()
    write_sensitive_rules(rules_path, capacity=5)
    db_path = runtime_rules_db_path(rules_path)
    depends.rules_manager = RulesManager(
        str(rules_path),
        store=SQLiteRuleStore(str(db_path), seed_config_path=str(rules_path)),
    )

    response = await client.put(
        "/admin/rules",
        headers={**ADMIN_HEADERS, "X-Audit-Actor": "alice@example.com"},
        json={
            "routes": {
                "/api/accounts/{account_id}/data": {
                    "global_limit": {
                        "rate": 0.001,
                        "capacity": 1,
                        "fail_mode": "open",
                        "sensitivity": "sensitive",
                    }
                }
            }
        },
    )
    assert response.status_code == 202
    approval_id = response.json()["approval_id"]

    restarted_manager = RulesManager(
        str(rules_path),
        store=SQLiteRuleStore(str(db_path), seed_config_path=str(rules_path)),
    )
    pending = restarted_manager.pending_updates()
    assert pending["requests"][0]["id"] == approval_id
    assert pending["requests"][0]["audit"]["actor"] == "alice@example.com"
    assert restarted_manager.snapshot()["rules"]["routes"]["/api/accounts/{account_id}/data"][
        "global_limit"
    ]["capacity"] == 5


@pytest.mark.asyncio
async def test_sensitive_rule_update_is_saved_pending_approval(client):
    rules_path = runtime_rules_path()
    write_sensitive_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))

    update_payload = {
        "routes": {
            "/api/accounts/{account_id}/data": {
                "global_limit": {
                    "rate": 0.001,
                    "capacity": 1,
                    "fail_mode": "open",
                    "sensitivity": "sensitive",
                    "owner": "accounts",
                }
            }
        }
    }

    response = await client.put(
        "/admin/rules",
        headers={
            **ADMIN_HEADERS,
            "X-Audit-Actor": "alice@example.com",
            "X-Audit-Reason": "tighten account-data limit",
        },
        json=update_payload,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["updated"] is False
    assert body["pending_approval"] is True
    assert body["version"] == 1
    assert body["sensitive_routes"] == ["/api/accounts/{account_id}/data"]

    snapshot = depends.rules_manager.snapshot()
    assert snapshot["rules"]["routes"]["/api/accounts/{account_id}/data"]["global_limit"][
        "capacity"
    ] == 5

    pending = (await client.get("/admin/rules/pending", headers=ADMIN_HEADERS)).json()
    assert len(pending["requests"]) == 1
    assert pending["requests"][0]["id"] == body["approval_id"]
    assert pending["requests"][0]["audit"]["actor"] == "alice@example.com"


@pytest.mark.asyncio
async def test_sensitive_rule_approval_requires_second_admin_and_then_applies(client):
    rules_path = runtime_rules_path()
    write_sensitive_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))

    update_payload = {
        "routes": {
            "/api/accounts/{account_id}/data": {
                "global_limit": {
                    "rate": 0.001,
                    "capacity": 1,
                    "fail_mode": "open",
                    "sensitivity": "sensitive",
                    "owner": "accounts",
                }
            }
        }
    }
    propose_response = await client.put(
        "/admin/rules",
        headers={**ADMIN_HEADERS, "X-Audit-Actor": "alice@example.com"},
        json=update_payload,
    )
    approval_id = propose_response.json()["approval_id"]

    same_actor_response = await client.post(
        f"/admin/rules/pending/{approval_id}/approve",
        headers={**ADMIN_HEADERS, "X-Audit-Actor": "alice@example.com"},
    )
    assert same_actor_response.status_code == 409

    approval_response = await client.post(
        f"/admin/rules/pending/{approval_id}/approve",
        headers={
            **ADMIN_HEADERS,
            "X-Audit-Actor": "bob@example.com",
            "X-Audit-Reason": "reviewed sensitive route change",
        },
    )
    assert approval_response.status_code == 200
    assert approval_response.json()["approved"] is True
    assert approval_response.json()["version"] == 2

    snapshot = depends.rules_manager.snapshot()
    assert snapshot["rules"]["routes"]["/api/accounts/{account_id}/data"]["global_limit"][
        "capacity"
    ] == 1

    pending = (await client.get("/admin/rules/pending", headers=ADMIN_HEADERS)).json()
    assert pending["requests"] == []

    resolved = (
        await client.get(
            "/admin/rules/pending",
            headers=ADMIN_HEADERS,
            params={"include_resolved": "true"},
        )
    ).json()
    assert resolved["requests"][0]["status"] == "approved"
    assert resolved["requests"][0]["approval_audit"]["actor"] == "bob@example.com"

    history = (await client.get("/admin/rules/history", headers=ADMIN_HEADERS)).json()
    assert history["versions"][-1]["action"] == "approve_sensitive_update"
    assert history["versions"][-1]["audit"]["actor"] == "bob@example.com"


@pytest.mark.asyncio
async def test_sensitive_rule_pending_update_can_be_rejected(client):
    rules_path = runtime_rules_path()
    write_sensitive_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))

    propose_response = await client.put(
        "/admin/rules",
        headers={**ADMIN_HEADERS, "X-Audit-Actor": "alice@example.com"},
        json={
            "routes": {
                "/api/accounts/{account_id}/data": {
                    "global_limit": {
                        "rate": 0.001,
                        "capacity": 1,
                        "fail_mode": "open",
                        "sensitivity": "sensitive",
                    }
                }
            }
        },
    )
    approval_id = propose_response.json()["approval_id"]

    reject_response = await client.post(
        f"/admin/rules/pending/{approval_id}/reject",
        headers={**ADMIN_HEADERS, "X-Audit-Actor": "carol@example.com"},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["rejected"] is True

    snapshot = depends.rules_manager.snapshot()
    assert snapshot["rules"]["routes"]["/api/accounts/{account_id}/data"]["global_limit"][
        "capacity"
    ] == 5

    resolved = (
        await client.get(
            "/admin/rules/pending",
            headers=ADMIN_HEADERS,
            params={"include_resolved": "true"},
        )
    ).json()
    assert resolved["requests"][0]["status"] == "rejected"
    assert resolved["requests"][0]["rejection_audit"]["actor"] == "carol@example.com"


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
async def test_rule_audit_filters_history_by_metadata(client):
    rules_path = runtime_rules_path()
    write_sensitive_rules(rules_path, capacity=5)
    depends.rules_manager = RulesManager(str(rules_path))

    propose_response = await client.put(
        "/admin/rules",
        headers={**ADMIN_HEADERS, "X-Audit-Actor": "alice@example.com"},
        json={
            "routes": {
                "/api/accounts/{account_id}/data": {
                    "global_limit": {
                        "rate": 0.001,
                        "capacity": 1,
                        "fail_mode": "open",
                        "sensitivity": "sensitive",
                    }
                }
            }
        },
    )
    approval_id = propose_response.json()["approval_id"]

    await client.post(
        f"/admin/rules/pending/{approval_id}/approve",
        headers={**ADMIN_HEADERS, "X-Audit-Actor": "bob@example.com"},
    )

    audit_response = await client.get(
        "/admin/rules/audit",
        headers=ADMIN_HEADERS,
        params={
            "route": "/api/accounts",
            "actor": "bob",
            "action": "approve_sensitive_update",
            "sensitivity": "sensitive",
            "limit": "5",
        },
    )

    assert audit_response.status_code == 200
    body = audit_response.json()
    assert body["filters"]["route"] == "/api/accounts"
    assert body["count"] == 1
    entry = body["entries"][0]
    assert entry["action"] == "approve_sensitive_update"
    assert entry["audit"]["actor"] == "bob@example.com"
    assert entry["changed_routes"] == [
        {
            "route": "/api/accounts/{account_id}/data",
            "change": "changed",
            "sensitivity": "sensitive",
        }
    ]

    no_match_response = await client.get(
        "/admin/rules/audit",
        headers=ADMIN_HEADERS,
        params={"sensitivity": "public"},
    )
    assert no_match_response.status_code == 200
    assert no_match_response.json()["entries"] == []


@pytest.mark.asyncio
async def test_rule_audit_rejects_invalid_time_range(client):
    response = await client.get(
        "/admin/rules/audit",
        headers=ADMIN_HEADERS,
        params={"since": "20", "until": "10"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rule_rollback_rejects_unknown_version(client):
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=2)
    depends.rules_manager = RulesManager(str(rules_path))

    response = await client.post("/admin/rules/rollback/999", headers=ADMIN_HEADERS)

    assert response.status_code == 422

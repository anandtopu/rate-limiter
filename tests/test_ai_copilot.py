import json
from pathlib import Path
from urllib.error import URLError
from uuid import uuid4

import pytest

import app.api.depends as depends
from app.ai.copilot import (
    CopilotConfigurationError,
    CopilotProviderError,
    PolicyCopilotInput,
    get_policy_copilot_adapter,
)
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


def sample_copilot_input():
    return PolicyCopilotInput(
        prompt="Explain current pressure.",
        active_rules={"routes": {}},
        feature_summary={"events_analyzed": 0},
        recommendations={"items": []},
        anomalies={"count": 0},
        safety_constraints=["dry-run only"],
    )


def patch_provider_response(monkeypatch, provider_response):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            if isinstance(provider_response, bytes):
                return provider_response
            return json.dumps(provider_response).encode("utf-8")

    def fake_urlopen(request, timeout):
        return FakeResponse()

    monkeypatch.setattr("app.ai.copilot.urlopen", fake_urlopen)


def test_openai_compatible_adapter_accepts_output_text_json(monkeypatch):
    patch_provider_response(
        monkeypatch,
        {
            "output_text": (
                "```json\n"
                '{"explanation":"Parsed from output_text","proposed_rules":null,'
                '"warnings":["check dry-run"]}'
                "\n```"
            )
        },
    )
    adapter = get_policy_copilot_adapter(
        enabled=True,
        provider="openai-compatible",
        endpoint="https://llm.local/v1/chat/completions",
    )

    result = adapter.generate(sample_copilot_input())

    assert result.explanation == "Parsed from output_text"
    assert result.proposed_rules is None
    assert result.warnings == ["check dry-run"]


def test_openai_compatible_adapter_rejects_invalid_response_json(monkeypatch):
    patch_provider_response(monkeypatch, b"not-json")
    adapter = get_policy_copilot_adapter(
        enabled=True,
        provider="openai_compatible",
        endpoint="https://llm.local/v1/chat/completions",
    )

    with pytest.raises(CopilotProviderError, match="returned invalid JSON"):
        adapter.generate(sample_copilot_input())


def test_openai_compatible_adapter_rejects_invalid_result_shape(monkeypatch):
    patch_provider_response(
        monkeypatch,
        {"choices": [{"message": {"content": json.dumps({"proposed_rules": None})}}]},
    )
    adapter = get_policy_copilot_adapter(
        enabled=True,
        provider="openai_compatible",
        endpoint="https://llm.local/v1/chat/completions",
    )

    with pytest.raises(CopilotProviderError, match="invalid result shape"):
        adapter.generate(sample_copilot_input())


def test_openai_compatible_adapter_rejects_missing_result(monkeypatch):
    patch_provider_response(monkeypatch, {"choices": []})
    adapter = get_policy_copilot_adapter(
        enabled=True,
        provider="openai_compatible",
        endpoint="https://llm.local/v1/chat/completions",
    )

    with pytest.raises(CopilotProviderError, match="did not include a copilot result"):
        adapter.generate(sample_copilot_input())


def test_openai_compatible_adapter_rejects_nonpositive_timeout():
    with pytest.raises(CopilotConfigurationError, match="timeout"):
        get_policy_copilot_adapter(
            enabled=True,
            provider="openai_compatible",
            endpoint="https://llm.local/v1/chat/completions",
            timeout_s=0,
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
async def test_policy_copilot_openai_compatible_provider_validates_returned_rules(
    client, monkeypatch
):
    settings.ai_copilot_enabled = True
    settings.ai_copilot_provider = "openai_compatible"
    settings.ai_copilot_endpoint = "https://llm.local/v1/chat/completions"
    settings.ai_copilot_api_key = "test-token"
    settings.ai_copilot_model = "test-model"
    settings.ai_copilot_timeout_s = 2.5
    rules_path = runtime_rules_path()
    write_rules(rules_path, capacity=5, rate=1)
    depends.rules_manager = RulesManager(str(rules_path))

    for _ in range(4):
        await client.get("/api/data", headers={"X-API-Key": "copilot_provider_user"})

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
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            content = json.dumps({
                "explanation": "Provider draft tightens /api/data after recent pressure.",
                "proposed_rules": proposed_rules,
                "warnings": ["Review dry-run output before approval."],
            })
            return json.dumps({
                "choices": [{"message": {"content": content}}],
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.ai.copilot.urlopen", fake_urlopen)

    response = await client.post(
        "/admin/ai/policy-copilot",
        headers=ADMIN_HEADERS,
        json={"prompt": "Draft a safer policy for current pressure."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai_compatible"
    assert body["explanation"] == "Provider draft tightens /api/data after recent pressure."
    assert body["warnings"] == ["Review dry-run output before approval."]
    assert body["proposed_rules"] == proposed_rules
    assert body["validation"]["valid"] is True
    assert body["dry_run"]["valid"] is True
    assert body["dry_run"]["applied"] is False
    assert body["dry_run"]["replay"]["summary"]["newly_denied"] > 0

    assert captured["url"] == "https://llm.local/v1/chat/completions"
    assert captured["timeout"] == 2.5
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["temperature"] == 0
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"][0]["role"] == "system"
    user_context = json.loads(captured["body"]["messages"][1]["content"])
    assert user_context["prompt"] == "Draft a safer policy for current pressure."
    assert user_context["safety_constraints"]
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["authorization"] == "Bearer test-token"

    snapshot = depends.rules_manager.snapshot()
    assert snapshot["rules"]["routes"]["/api/data"]["global_limit"]["capacity"] == 5


@pytest.mark.asyncio
async def test_policy_copilot_openai_compatible_requires_endpoint(client):
    settings.ai_copilot_enabled = True
    settings.ai_copilot_provider = "openai_compatible"

    response = await client.post(
        "/admin/ai/policy-copilot",
        headers=ADMIN_HEADERS,
        json={"prompt": "Explain current limiter pressure."},
    )

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "AI policy copilot provider requires AI_COPILOT_ENDPOINT"
    )


@pytest.mark.asyncio
async def test_policy_copilot_provider_runtime_failure_is_bad_gateway(
    client, monkeypatch
):
    settings.ai_copilot_enabled = True
    settings.ai_copilot_provider = "openai_compatible"
    settings.ai_copilot_endpoint = "https://llm.local/v1/chat/completions"

    def fake_urlopen(request, timeout):
        raise URLError("provider unavailable")

    monkeypatch.setattr("app.ai.copilot.urlopen", fake_urlopen)

    response = await client.post(
        "/admin/ai/policy-copilot",
        headers=ADMIN_HEADERS,
        json={"prompt": "Explain current limiter pressure."},
    )

    assert response.status_code == 502
    assert "AI policy copilot provider request failed" in response.json()["detail"]


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

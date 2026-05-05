import pytest_asyncio
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient

import app.api.depends as depends
from app.ai.telemetry import telemetry_hub
from app.config import settings
from app.core.limiter import RedisRateLimiter
from app.core.rules import RulesManager
from app.main import app
from app.observability.metrics import metrics_registry


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
    app.state.redis_client = redis_client
    metrics_registry.reset()
    telemetry_hub.reset()
    telemetry_hub.set_store(None)
    settings.hash_identifiers = False
    settings.rule_store_backend = "json"
    settings.rule_store_db_path = "data/rules.sqlite3"
    settings.trusted_proxy_ips = ""
    settings.expose_demo_dashboard = True
    settings.enable_tracing = False
    settings.trace_console_exporter = True
    settings.trace_otlp_enabled = False
    settings.trace_otlp_endpoint = None
    settings.trace_otlp_headers = None
    settings.trace_otlp_timeout_s = 10.0
    settings.persist_telemetry = False
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    settings.hash_identifiers = False
    settings.rule_store_backend = "json"
    settings.rule_store_db_path = "data/rules.sqlite3"
    settings.trusted_proxy_ips = ""
    settings.expose_demo_dashboard = True
    settings.enable_tracing = False
    settings.trace_console_exporter = True
    settings.trace_otlp_enabled = False
    settings.trace_otlp_endpoint = None
    settings.trace_otlp_headers = None
    settings.trace_otlp_timeout_s = 10.0
    settings.persist_telemetry = False
    telemetry_hub.set_store(None)

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    # Local demo default; override ADMIN_API_KEY outside demos.
    admin_api_key: str = "dev-admin-key"
    # Optional comma-separated named keys, e.g. "primary:key-one,backup:key-two".
    admin_api_keys: str = ""
    rules_path: str = "rules.json"
    rule_store_backend: str = "json"
    rule_store_db_path: str = "data/rules.sqlite3"
    expose_demo_dashboard: bool = True
    hash_identifiers: bool = False
    trusted_proxy_ips: str = ""
    enable_tracing: bool = False
    trace_service_name: str = "portfolio-rate-limiter"
    trace_console_exporter: bool = True
    trace_otlp_enabled: bool = False
    trace_otlp_endpoint: str | None = None
    trace_otlp_headers: str | None = None
    trace_otlp_timeout_s: float = 10.0
    persist_telemetry: bool = False
    telemetry_db_path: str = "data/telemetry.sqlite3"
    ai_copilot_enabled: bool = False
    ai_copilot_provider: str = "fake"
    ai_copilot_timeout_s: float = 10.0

settings = Settings()

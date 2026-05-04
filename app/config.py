from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    # Local demo default; override ADMIN_API_KEY outside demos.
    admin_api_key: str = "dev-admin-key"
    rules_path: str = "rules.json"
    expose_demo_dashboard: bool = True
    hash_identifiers: bool = False
    enable_tracing: bool = False
    trace_service_name: str = "portfolio-rate-limiter"
    trace_console_exporter: bool = True
    persist_telemetry: bool = False
    telemetry_db_path: str = "data/telemetry.sqlite3"

settings = Settings()

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import redis.asyncio as redis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import app.api.depends as depends
from app.ai.telemetry import telemetry_hub
from app.api.admin import router as admin_router
from app.api.security import require_admin_key
from app.config import settings
from app.core.limiter import RedisRateLimiter
from app.core.rules import RulesManager
from app.observability.logging import configure_logging
from app.observability.metrics import metrics_registry
from app.observability.telemetry_store import SQLiteTelemetryStore
from app.observability.tracing import configure_tracing, current_trace_id, start_span


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_logging()
    configure_tracing(
        enabled=settings.enable_tracing,
        service_name=settings.trace_service_name,
        console_exporter=settings.trace_console_exporter,
        otlp_enabled=settings.trace_otlp_enabled,
        otlp_endpoint=settings.trace_otlp_endpoint,
        otlp_headers=settings.trace_otlp_headers,
        otlp_timeout_s=settings.trace_otlp_timeout_s,
    )
    if settings.persist_telemetry:
        telemetry_hub.set_store(SQLiteTelemetryStore(settings.telemetry_db_path))
    redis_client = redis.from_url(settings.redis_url)
    app.state.redis_client = redis_client
    depends.redis_limiter = RedisRateLimiter(redis_client)
    depends.rules_manager = RulesManager(settings.rules_path)
    yield
    # Shutdown
    await redis_client.aclose()

app = FastAPI(title="Distributed Rate Limiter API", lifespan=lifespan)
app.include_router(admin_router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    configure_tracing(
        enabled=settings.enable_tracing,
        service_name=settings.trace_service_name,
        console_exporter=settings.trace_console_exporter,
        otlp_enabled=settings.trace_otlp_enabled,
        otlp_endpoint=settings.trace_otlp_endpoint,
        otlp_headers=settings.trace_otlp_headers,
        otlp_timeout_s=settings.trace_otlp_timeout_s,
    )
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    with start_span(
        "http.request",
        {
            "http.request.method": request.method,
            "url.path": request.url.path,
            "request.id": request_id,
        },
    ):
        request.state.trace_id = current_trace_id()
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    if request.state.trace_id:
        response.headers["X-Trace-ID"] = request.state.trace_id
    return response


@app.exception_handler(depends.RateLimitExceededException)
async def rate_limit_handler(request: Request, exc: depends.RateLimitExceededException):
    return JSONResponse(
        status_code=429,
        content={"error": "Too Many Requests", "message": "Rate limit exceeded."},
        headers=exc.headers
    )

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/ready")
async def readiness_check(request: Request):
    redis_client = getattr(request.app.state, "redis_client", None)
    if not redis_client:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "redis": "unavailable"},
        )

    try:
        await redis_client.ping()
    except redis.RedisError:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "redis": "unavailable"},
        )

    return {"status": "ready", "redis": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(metrics_registry.render_prometheus(), media_type="text/plain")


@app.get("/demo", include_in_schema=False)
async def demo_dashboard():
    if not settings.expose_demo_dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo dashboard is disabled",
        )

    return FileResponse(STATIC_DIR / "demo.html")


@app.get("/api/limited-health", dependencies=[Depends(depends.rate_limit)])
async def limited_health_check():
    return {"status": "ok", "limited": True}


@app.get("/api/data", dependencies=[Depends(depends.rate_limit)])
async def get_data():
    return {"data": "Protected resource"}

@app.get("/ai/signals", dependencies=[Depends(require_admin_key)])
async def ai_signals():
    return telemetry_hub.snapshot()

@app.post("/ai/recommendations", dependencies=[Depends(require_admin_key)])
async def ai_recommendations():
    return telemetry_hub.generate_recommendations()

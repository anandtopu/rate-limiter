from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
import redis.asyncio as redis
from app.config import settings
from app.core.limiter import RedisRateLimiter
from app.core.rules import RulesManager
import app.api.depends as depends
from app.ai.telemetry import telemetry_hub

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    redis_client = redis.from_url(settings.redis_url)
    depends.redis_limiter = RedisRateLimiter(redis_client)
    depends.rules_manager = RulesManager("rules.json")
    yield
    # Shutdown
    await redis_client.aclose()

app = FastAPI(title="Distributed Rate Limiter API", lifespan=lifespan)

@app.exception_handler(depends.RateLimitExceededException)
async def rate_limit_handler(request: Request, exc: depends.RateLimitExceededException):
    return JSONResponse(
        status_code=429,
        content={"error": "Too Many Requests", "message": "Rate limit exceeded."},
        headers=exc.headers
    )

@app.get("/health", dependencies=[Depends(depends.rate_limit)])
async def health_check():
    return {"status": "ok"}

@app.get("/api/data", dependencies=[Depends(depends.rate_limit)])
async def get_data():
    return {"data": "Protected resource"}

@app.get("/ai/signals")
async def ai_signals():
    return telemetry_hub.snapshot()

@app.post("/ai/recommendations")
async def ai_recommendations():
    return telemetry_hub.generate_recommendations()

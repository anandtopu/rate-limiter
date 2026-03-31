import time
from fastapi import Request, Response
from typing import Optional
from app.core.limiter import RedisRateLimiter
from app.core.rules import RulesManager
from app.ai.telemetry import record_rate_limit_decision

redis_limiter: Optional[RedisRateLimiter] = None
rules_manager: Optional[RulesManager] = None

class RateLimitExceededException(Exception):
    def __init__(self, headers: dict):
        self.headers = headers

async def rate_limit(request: Request, response: Response):
    if not redis_limiter or not rules_manager:
        return
        
    client_ip = request.client.host if request.client else "127.0.0.1"
    api_key = request.headers.get("X-API-Key")
    identifier = api_key if api_key else client_ip

    route_path = request.url.path
    rule = rules_manager.get_rule(route_path, identifier)

    key = f"rate_limit:{route_path}:{identifier}"
    allowed, remaining, redis_fail_open = await redis_limiter.is_allowed(key, rate=rule.rate, capacity=rule.capacity)

    time_to_full = (rule.capacity - remaining) / rule.rate if rule.rate > 0 else 0
    reset_timestamp = int(time.time() + time_to_full)

    headers = {
        "X-RateLimit-Limit": str(rule.capacity),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_timestamp)
    }
    
    for k, v in headers.items():
        response.headers[k] = v

    if not allowed:
        headers["Retry-After"] = str(int(time_to_full)) if time_to_full > 0 else "1"
        record_rate_limit_decision(
            route_path=route_path,
            identifier=identifier,
            allowed=False,
            remaining=remaining,
            capacity=rule.capacity,
            rate=rule.rate,
            retry_after_s=int(time_to_full) if time_to_full > 0 else 1,
            redis_fail_open=redis_fail_open,
        )
        raise RateLimitExceededException(headers=headers)

    record_rate_limit_decision(
        route_path=route_path,
        identifier=identifier,
        allowed=True,
        remaining=remaining,
        capacity=rule.capacity,
        rate=rule.rate,
        retry_after_s=None,
        redis_fail_open=redis_fail_open,
    )

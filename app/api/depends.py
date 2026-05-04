import hashlib
import math

from fastapi import Request, Response

from app.ai.telemetry import record_rate_limit_decision
from app.config import settings
from app.core.limiter import RedisRateLimiter
from app.core.rules import RulesManager
from app.observability.logging import log_rate_limit_decision
from app.observability.metrics import record_rate_limit_metric
from app.observability.tracing import mark_span_error, set_span_attributes, start_span

redis_limiter: RedisRateLimiter | None = None
rules_manager: RulesManager | None = None

class RateLimitExceededException(Exception):
    def __init__(self, headers: dict):
        self.headers = headers


def build_rate_limit_headers(
    capacity: int,
    remaining: float,
    reset_timestamp: int,
    algorithm: str,
) -> dict:
    return {
        "X-RateLimit-Limit": str(capacity),
        "X-RateLimit-Remaining": str(max(0, math.floor(remaining))),
        "X-RateLimit-Reset": str(reset_timestamp),
        "X-RateLimit-Algorithm": algorithm,
    }


def protected_identifier(identifier: str) -> str:
    if not settings.hash_identifiers:
        return identifier

    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


async def rate_limit(request: Request, response: Response):
    if not redis_limiter or not rules_manager:
        return
        
    client_ip = request.client.host if request.client else "127.0.0.1"
    api_key = request.headers.get("X-API-Key")
    identifier = api_key if api_key else client_ip

    route_path = request.url.path
    rule = rules_manager.get_rule(route_path, identifier)
    metric_identifier = protected_identifier(identifier)

    key = f"rate_limit:{rule.algorithm}:{route_path}:{metric_identifier}"
    with start_span(
        "rate_limit.decision",
        {
            "rate_limit.route": route_path,
            "rate_limit.identifier": metric_identifier,
            "rate_limit.algorithm": rule.algorithm,
            "rate_limit.capacity": rule.capacity,
            "rate_limit.rate": rule.rate,
            "rate_limit.fail_mode": rule.fail_mode,
        },
    ):
        result = await redis_limiter.is_allowed(
            key,
            rate=rule.rate,
            capacity=rule.capacity,
            fail_mode=rule.fail_mode,
            algorithm=rule.algorithm,
        )
        set_span_attributes({
            "rate_limit.allowed": result.allowed,
            "rate_limit.remaining": result.remaining,
            "rate_limit.redis_failed": result.redis_failed,
            "rate_limit.redis_fail_open": result.redis_fail_open,
        })
        if not result.allowed:
            mark_span_error("rate limit exceeded")

    headers = build_rate_limit_headers(
        capacity=rule.capacity,
        remaining=result.remaining,
        reset_timestamp=result.reset_timestamp,
        algorithm=rule.algorithm,
    )
    
    for k, v in headers.items():
        response.headers[k] = v

    remaining_for_telemetry = max(0, math.floor(result.remaining))
    request_id = getattr(request.state, "request_id", None)

    if not result.allowed:
        retry_after_s = result.retry_after_s if result.retry_after_s is not None else 1
        headers["Retry-After"] = str(retry_after_s)
        record_rate_limit_decision(
            route_path=route_path,
            identifier=metric_identifier,
            allowed=False,
            remaining=remaining_for_telemetry,
            capacity=rule.capacity,
            rate=rule.rate,
            retry_after_s=retry_after_s,
            redis_fail_open=result.redis_fail_open,
        )
        record_rate_limit_metric(
            route_path=route_path,
            allowed=False,
            redis_failed=result.redis_failed,
            redis_fail_open=result.redis_fail_open,
        )
        log_rate_limit_decision(
            request_id=request_id,
            route=route_path,
            decision="denied",
            identifier=metric_identifier,
            remaining=remaining_for_telemetry,
            capacity=rule.capacity,
            fail_mode=rule.fail_mode,
            algorithm=rule.algorithm,
            redis_failed=result.redis_failed,
            redis_fail_open=result.redis_fail_open,
        )
        raise RateLimitExceededException(headers=headers)

    record_rate_limit_decision(
        route_path=route_path,
        identifier=metric_identifier,
        allowed=True,
        remaining=remaining_for_telemetry,
        capacity=rule.capacity,
        rate=rule.rate,
        retry_after_s=None,
        redis_fail_open=result.redis_fail_open,
    )
    record_rate_limit_metric(
        route_path=route_path,
        allowed=True,
        redis_failed=result.redis_failed,
        redis_fail_open=result.redis_fail_open,
    )
    log_rate_limit_decision(
        request_id=request_id,
        route=route_path,
        decision="allowed",
        identifier=metric_identifier,
        remaining=remaining_for_telemetry,
        capacity=rule.capacity,
        fail_mode=rule.fail_mode,
        algorithm=rule.algorithm,
        redis_failed=result.redis_failed,
        redis_fail_open=result.redis_fail_open,
    )

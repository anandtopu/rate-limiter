from typing import Literal

from pydantic import BaseModel, Field


class RateLimitRule(BaseModel):
    rate: float = Field(..., gt=0, description="Tokens to add per second")
    capacity: int = Field(..., gt=0, description="Maximum burst capacity of the bucket")
    algorithm: Literal["token_bucket", "fixed_window"] = "token_bucket"
    fail_mode: Literal["open", "closed"] = "open"
    description: str | None = None
    tier: str | None = None
    owner: str | None = None
    sensitivity: Literal["public", "internal", "sensitive"] | None = None

class RouteLimits(BaseModel):
    global_limit: RateLimitRule
    # Custom limits based on identifier types (ip, user_id, api_key)
    # The key is the identifier value, the value is the specific rule to apply
    overrides: dict[str, RateLimitRule] | None = None

class RateLimitConfig(BaseModel):
    routes: dict[str, RouteLimits]

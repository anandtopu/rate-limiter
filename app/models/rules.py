from pydantic import BaseModel, Field
from typing import Dict, Optional

class RateLimitRule(BaseModel):
    rate: float = Field(..., description="Tokens to add per second")
    capacity: int = Field(..., description="Maximum burst capacity of the bucket")

class RouteLimits(BaseModel):
    global_limit: RateLimitRule
    # Custom limits based on identifier types (ip, user_id, api_key)
    # The key is the identifier value, the value is the specific rule to apply
    overrides: Optional[Dict[str, RateLimitRule]] = None

class RateLimitConfig(BaseModel):
    routes: Dict[str, RouteLimits]

import time
import redis.asyncio as redis
from typing import Tuple

TOKEN_BUCKET_SCRIPT = """
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local fill_time = capacity / rate
local ttl = math.floor(fill_time * 2)
if ttl < 60 then
    ttl = 60
end

local last_tokens = tonumber(redis.call("HGET", KEYS[1], "tokens"))
if last_tokens == nil then
  last_tokens = capacity
end

local last_refilled = tonumber(redis.call("HGET", KEYS[1], "last_refill"))
if last_refilled == nil then
  last_refilled = now
end

local delta = math.max(0, now - last_refilled)
local filled_tokens = math.min(capacity, last_tokens + (delta * rate))

local allowed = filled_tokens >= requested
local new_tokens = filled_tokens
if allowed then
  new_tokens = filled_tokens - requested
end

redis.call("HSET", KEYS[1], "tokens", new_tokens)
redis.call("HSET", KEYS[1], "last_refill", now)
redis.call("EXPIRE", KEYS[1], ttl)

return { allowed and 1 or 0, new_tokens }
"""

class RedisRateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.script = self.redis.register_script(TOKEN_BUCKET_SCRIPT)

    async def is_allowed(self, key: str, rate: float, capacity: int, requested: int = 1) -> Tuple[bool, int]:
        """
        Check if a request is allowed based on the Token Bucket algorithm.
        rate: tokens per second
        capacity: max tokens in the bucket
        """
        now = time.time()
        
        try:
            result = await self.script(
                keys=[key],
                args=[rate, capacity, now, requested]
            )
            allowed_int, updated_tokens = result
            # updated_tokens might be a float in some Redis Lua returns, depending on math
            return bool(allowed_int), int(updated_tokens)
        except redis.RedisError as e:
            # Concept: Fail-open strategy. If Redis is down, we allow the request.
            # Logging should catch this in production.
            print(f"Redis error: {e}. Failing open.")
            return True, capacity - requested

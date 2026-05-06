import math
import time
from dataclasses import dataclass
from typing import Literal

import redis.asyncio as redis

# Redis Lua script uses token bucket field names; it does not contain credentials.
TOKEN_BUCKET_SCRIPT = (  # nosec B105
    """
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

local missing_tokens = requested - filled_tokens
local retry_after = 0
if not allowed then
  retry_after = math.ceil(missing_tokens / rate)
  if retry_after < 1 then
    retry_after = 1
  end
end

local time_to_full = (capacity - new_tokens) / rate
local reset_timestamp = math.ceil(now + time_to_full)

redis.call("HSET", KEYS[1], "tokens", new_tokens)
redis.call("HSET", KEYS[1], "last_refill", now)
redis.call("EXPIRE", KEYS[1], ttl)

return { allowed and 1 or 0, tostring(new_tokens), retry_after, reset_timestamp }
"""
)

FIXED_WINDOW_SCRIPT = """
local capacity = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local window_seconds = tonumber(ARGV[4])

local current = tonumber(redis.call("GET", KEYS[1]))
if current == nil then
  current = 0
end

local ttl = tonumber(redis.call("TTL", KEYS[1]))
if ttl == nil or ttl < 0 then
  ttl = window_seconds
end

local allowed = (current + requested) <= capacity
if allowed then
  current = redis.call("INCRBY", KEYS[1], requested)
  if current == requested then
    redis.call("EXPIRE", KEYS[1], window_seconds)
    ttl = window_seconds
  else
    ttl = tonumber(redis.call("TTL", KEYS[1]))
    if ttl == nil or ttl < 0 then
      ttl = window_seconds
      redis.call("EXPIRE", KEYS[1], window_seconds)
    end
  end
end

local remaining = capacity - current
if remaining < 0 then
  remaining = 0
end

local retry_after = 0
if not allowed then
  retry_after = ttl
  if retry_after < 1 then
    retry_after = 1
  end
end

local reset_timestamp = math.ceil(now + ttl)

return { allowed and 1 or 0, tostring(remaining), retry_after, reset_timestamp }
"""

SLIDING_WINDOW_SCRIPT = """
local capacity = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local window_seconds = tonumber(ARGV[4])
local request_id = ARGV[5]

local window_start = now - window_seconds
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", window_start)

local current = tonumber(redis.call("ZCARD", KEYS[1]))
local allowed = (current + requested) <= capacity

if allowed then
  for i = 1, requested do
    redis.call("ZADD", KEYS[1], now, request_id .. ":" .. i)
  end
  current = current + requested
end

redis.call("EXPIRE", KEYS[1], math.ceil(window_seconds * 2))

local remaining = capacity - current
if remaining < 0 then
  remaining = 0
end

local retry_after = 0
local reset_timestamp = math.ceil(now + window_seconds)
if not allowed then
  local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
  if oldest[2] ~= nil then
    retry_after = math.ceil((tonumber(oldest[2]) + window_seconds) - now)
  end
  if retry_after < 1 then
    retry_after = 1
  end
  reset_timestamp = math.ceil(now + retry_after)
elseif current > 0 then
  local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
  if oldest[2] ~= nil then
    reset_timestamp = math.ceil(tonumber(oldest[2]) + window_seconds)
  end
end

return { allowed and 1 or 0, tostring(remaining), retry_after, reset_timestamp }
"""


@dataclass(frozen=True)
class LimiterResult:
    allowed: bool
    remaining: float
    retry_after_s: int | None
    reset_timestamp: int
    redis_failed: bool = False
    redis_fail_open: bool = False


class RedisRateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.token_bucket_script = self.redis.register_script(TOKEN_BUCKET_SCRIPT)
        self.fixed_window_script = self.redis.register_script(FIXED_WINDOW_SCRIPT)
        self.sliding_window_script = self.redis.register_script(SLIDING_WINDOW_SCRIPT)
        self._request_sequence = 0

    async def is_allowed(
        self,
        key: str,
        rate: float,
        capacity: int,
        requested: int = 1,
        fail_mode: Literal["open", "closed"] = "open",
        algorithm: Literal["token_bucket", "fixed_window", "sliding_window"] = "token_bucket",
    ) -> LimiterResult:
        """
        Check if a request is allowed based on the Token Bucket algorithm.
        rate: tokens per second
        capacity: max tokens in the bucket
        """
        now = time.time()
        
        try:
            if algorithm == "fixed_window":
                window_seconds = max(1, math.ceil(capacity / rate))
                result = await self.fixed_window_script(
                    keys=[key],
                    args=[capacity, now, requested, window_seconds],
                )
            elif algorithm == "sliding_window":
                window_seconds = max(1, math.ceil(capacity / rate))
                self._request_sequence += 1
                request_id = f"{now}:{id(self)}:{self._request_sequence}"
                result = await self.sliding_window_script(
                    keys=[key],
                    args=[capacity, now, requested, window_seconds, request_id],
                )
            else:
                result = await self.token_bucket_script(
                    keys=[key],
                    args=[rate, capacity, now, requested],
                )
            allowed_int, updated_tokens, retry_after_s, reset_timestamp = result
            allowed = bool(int(allowed_int))
            return LimiterResult(
                allowed=allowed,
                remaining=max(0.0, float(updated_tokens)),
                retry_after_s=None if allowed else int(retry_after_s),
                reset_timestamp=int(reset_timestamp),
            )
        except redis.RedisError as e:
            print(f"Redis error: {e}. Failing {fail_mode}.")
            if fail_mode == "closed":
                return LimiterResult(
                    allowed=False,
                    remaining=0,
                    retry_after_s=1,
                    reset_timestamp=math.ceil(now + 1),
                    redis_failed=True,
                    redis_fail_open=False,
                )

            remaining = max(0, capacity - requested)
            if algorithm in {"fixed_window", "sliding_window"}:
                time_to_full = math.ceil(capacity / rate)
            else:
                time_to_full = (capacity - remaining) / rate
            return LimiterResult(
                allowed=True,
                remaining=remaining,
                retry_after_s=None,
                reset_timestamp=math.ceil(now + time_to_full),
                redis_failed=True,
                redis_fail_open=True,
            )

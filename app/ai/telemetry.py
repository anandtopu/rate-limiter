import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RateLimitEvent:
    timestamp: float
    route_path: str
    identifier: str
    allowed: bool
    remaining: int
    capacity: int
    rate: float
    retry_after_s: int | None
    redis_fail_open: bool


class TelemetryHub:
    def __init__(self, window_seconds: int = 300, max_events: int = 50_000):
        self.window_seconds = window_seconds
        self.max_events = max_events
        self.store: Any = None
        self._persistent_errors: int = 0
        self._events: deque[RateLimitEvent] = deque()

        self._total_by_route: Counter[str] = Counter()
        self._limited_by_route: Counter[str] = Counter()
        self._limited_by_identifier: Counter[str] = Counter()
        self._limited_by_route_identifier: Counter[tuple[str, str]] = Counter()

        self._redis_fail_open_by_route: Counter[str] = Counter()
        self._redis_fail_open_total: int = 0

        self._last_recommendations: dict[str, Any] = {"generated_at": 0, "items": []}

    def reset(self) -> None:
        store = self.store
        self.__init__(window_seconds=self.window_seconds, max_events=self.max_events)
        self.store = store

    def set_store(self, store: Any) -> None:
        self.store = store

    def _gc(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and (
            self._events[0].timestamp < cutoff or len(self._events) > self.max_events
        ):
            ev = self._events.popleft()
            self._total_by_route[ev.route_path] -= 1
            if self._total_by_route[ev.route_path] <= 0:
                del self._total_by_route[ev.route_path]

            if not ev.allowed:
                self._limited_by_route[ev.route_path] -= 1
                if self._limited_by_route[ev.route_path] <= 0:
                    del self._limited_by_route[ev.route_path]

                self._limited_by_identifier[ev.identifier] -= 1
                if self._limited_by_identifier[ev.identifier] <= 0:
                    del self._limited_by_identifier[ev.identifier]

                key = (ev.route_path, ev.identifier)
                self._limited_by_route_identifier[key] -= 1
                if self._limited_by_route_identifier[key] <= 0:
                    del self._limited_by_route_identifier[key]

            if ev.redis_fail_open:
                self._redis_fail_open_total -= 1
                self._redis_fail_open_by_route[ev.route_path] -= 1
                if self._redis_fail_open_by_route[ev.route_path] <= 0:
                    del self._redis_fail_open_by_route[ev.route_path]

    def record(self, event: RateLimitEvent) -> None:
        self._events.append(event)
        self._total_by_route[event.route_path] += 1

        if not event.allowed:
            self._limited_by_route[event.route_path] += 1
            self._limited_by_identifier[event.identifier] += 1
            self._limited_by_route_identifier[(event.route_path, event.identifier)] += 1

        if event.redis_fail_open:
            self._redis_fail_open_total += 1
            self._redis_fail_open_by_route[event.route_path] += 1

        if self.store:
            try:
                self.store.record(event)
            except Exception:
                self._persistent_errors += 1

        self._gc(event.timestamp)

    def persistent_summary(self) -> dict[str, Any]:
        if not self.store:
            return {"enabled": False}

        try:
            summary = self.store.summary()
        except Exception:
            self._persistent_errors += 1
            return {
                "enabled": True,
                "status": "unavailable",
                "persistent_errors": self._persistent_errors,
            }

        return {
            "enabled": True,
            "persistent_errors": self._persistent_errors,
            **summary,
        }

    def persistent_recent(self, limit: int = 100) -> dict[str, Any]:
        if not self.store:
            return {"enabled": False, "events": []}

        try:
            events = self.store.recent(limit=limit)
        except Exception:
            self._persistent_errors += 1
            events = []

        return {"enabled": True, "events": events}

    def snapshot(self, top_n: int = 10) -> dict[str, Any]:
        now = time.time()
        self._gc(now)

        def pct(n: int, d: int) -> float:
            if d <= 0:
                return 0.0
            return round((n / d) * 100.0, 2)

        routes = []
        for route, total in self._total_by_route.most_common(top_n):
            limited = self._limited_by_route.get(route, 0)
            routes.append({
                "route": route,
                "requests": total,
                "rate_limited": limited,
                "rate_limited_pct": pct(limited, total),
                "redis_fail_open": self._redis_fail_open_by_route.get(route, 0),
            })

        offenders = []
        for identifier, limited in self._limited_by_identifier.most_common(top_n):
            offenders.append({"identifier": identifier, "rate_limited": limited})

        hot_pairs = []
        for (route, identifier), limited in self._limited_by_route_identifier.most_common(top_n):
            hot_pairs.append({"route": route, "identifier": identifier, "rate_limited": limited})

        return {
            "window_seconds": self.window_seconds,
            "events_in_window": len(self._events),
            "routes": routes,
            "top_offenders": offenders,
            "hot_pairs": hot_pairs,
            "redis_fail_open_total": self._redis_fail_open_total,
            "recommendations": self._last_recommendations,
        }

    def recent_events(self) -> list[RateLimitEvent]:
        now = time.time()
        self._gc(now)
        return list(self._events)

    def generate_recommendations(self) -> dict[str, Any]:
        now = time.time()
        self._gc(now)

        items: list[dict[str, Any]] = []

        for route, total in self._total_by_route.items():
            limited = self._limited_by_route.get(route, 0)
            if total < 20:
                continue
            limited_ratio = limited / max(1, total)

            if limited_ratio >= 0.15:
                items.append({
                    "type": "tuning",
                    "route": route,
                    "severity": "high" if limited_ratio >= 0.3 else "medium",
                    "signal": {
                        "requests": total,
                        "rate_limited": limited,
                        "rate_limited_ratio": round(limited_ratio, 4),
                    },
                    "recommendation": {
                        "action": "review_limits",
                        "message": (
                            "High 429 ratio suggests rule may be too strict for current "
                            "traffic or clients are misbehaving."
                        ),
                        "suggested_next_steps": [
                            (
                                "Check if this endpoint is called by polling loops or "
                                "retries without backoff"
                            ),
                            (
                                "If traffic is legitimate, consider increasing capacity "
                                "(burst) or rate (sustained)"
                            ),
                            (
                                "If traffic is abusive, add identifier-specific overrides "
                                "or upstream WAF rules"
                            ),
                        ],
                    },
                })

        if self._redis_fail_open_total > 0:
            items.append({
                "type": "reliability",
                "severity": "high",
                "signal": {"redis_fail_open_total": self._redis_fail_open_total},
                "recommendation": {
                    "action": "investigate_redis",
                    "message": (
                        "Fail-open events detected. Rate limiting may be bypassed when "
                        "Redis is unhealthy."
                    ),
                    "suggested_next_steps": [
                        "Check Redis connectivity / auth / maxclients",
                        "Add alerting on redis_fail_open_total",
                        "Consider switching fail-open to fail-closed for sensitive endpoints",
                    ],
                },
            })

        self._last_recommendations = {"generated_at": int(now), "items": items}
        return self._last_recommendations


telemetry_hub = TelemetryHub()


def record_rate_limit_decision(
    *,
    route_path: str,
    identifier: str,
    allowed: bool,
    remaining: int,
    capacity: int,
    rate: float,
    retry_after_s: int | None,
    redis_fail_open: bool,
) -> None:
    telemetry_hub.record(
        RateLimitEvent(
            timestamp=time.time(),
            route_path=route_path,
            identifier=identifier,
            allowed=allowed,
            remaining=remaining,
            capacity=capacity,
            rate=rate,
            retry_after_s=retry_after_s,
            redis_fail_open=redis_fail_open,
        )
    )

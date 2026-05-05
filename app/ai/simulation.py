import math
from typing import Any

from app.models.rules import RateLimitConfig, RateLimitRule


def _field(event: Any, name: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


def _event_timestamp(event: Any, fallback: float) -> float:
    value = _field(event, "timestamp")
    return float(value) if value is not None else fallback


def _event_route(event: Any) -> str:
    return str(_field(event, "route_path", "unknown"))


def _event_identifier(event: Any) -> str:
    return str(_field(event, "identifier", "unknown"))


def _event_allowed(event: Any) -> bool:
    return bool(_field(event, "allowed", False))


def _route_rule(config: RateLimitConfig, route: str, identifier: str) -> RateLimitRule | None:
    route_limits = config.routes.get(route)
    if not route_limits:
        return None
    if route_limits.overrides and identifier in route_limits.overrides:
        return route_limits.overrides[identifier]
    return route_limits.global_limit


class ReplayBucket:
    def __init__(self, rule: RateLimitRule, first_timestamp: float):
        self.rule = rule
        self.tokens = float(rule.capacity)
        self.last_timestamp = first_timestamp
        self.fixed_window_start = first_timestamp
        self.fixed_window_count = 0
        self.sliding_timestamps: list[float] = []

    @property
    def window_seconds(self) -> int:
        return max(1, math.ceil(self.rule.capacity / self.rule.rate))

    def allow(self, timestamp: float) -> bool:
        if self.rule.algorithm == "fixed_window":
            return self._allow_fixed_window(timestamp)
        if self.rule.algorithm == "sliding_window":
            return self._allow_sliding_window(timestamp)
        return self._allow_token_bucket(timestamp)

    def _allow_token_bucket(self, timestamp: float) -> bool:
        elapsed = max(0.0, timestamp - self.last_timestamp)
        self.tokens = min(float(self.rule.capacity), self.tokens + elapsed * self.rule.rate)
        self.last_timestamp = timestamp
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    def _allow_fixed_window(self, timestamp: float) -> bool:
        if timestamp - self.fixed_window_start >= self.window_seconds:
            elapsed_windows = math.floor(
                (timestamp - self.fixed_window_start) / self.window_seconds
            )
            self.fixed_window_start += elapsed_windows * self.window_seconds
            self.fixed_window_count = 0
        if self.fixed_window_count < self.rule.capacity:
            self.fixed_window_count += 1
            return True
        return False

    def _allow_sliding_window(self, timestamp: float) -> bool:
        cutoff = timestamp - self.window_seconds
        self.sliding_timestamps = [item for item in self.sliding_timestamps if item > cutoff]
        if len(self.sliding_timestamps) < self.rule.capacity:
            self.sliding_timestamps.append(timestamp)
            return True
        return False


def replay_policy(
    *,
    active_config: RateLimitConfig,
    proposed_config: RateLimitConfig,
    events: list[Any],
) -> dict[str, Any]:
    ordered_events = sorted(
        list(events),
        key=lambda event: (
            _event_timestamp(event, 0.0),
            _event_route(event),
            _event_identifier(event),
        ),
    )
    active_buckets: dict[tuple[str, str], ReplayBucket] = {}
    proposed_buckets: dict[tuple[str, str], ReplayBucket] = {}
    route_rows: dict[str, dict[str, Any]] = {}
    identifier_rows: dict[str, dict[str, Any]] = {}
    sensitive_routes: set[str] = set()

    def row(container: dict[str, dict[str, Any]], key: str, field_name: str) -> dict[str, Any]:
        if key not in container:
            container[key] = {
                field_name: key,
                "events": 0,
                "observed_denied": 0,
                "active_replay_denied": 0,
                "proposed_replay_denied": 0,
                "newly_denied": 0,
                "newly_allowed": 0,
            }
        return container[key]

    for index, event in enumerate(ordered_events):
        timestamp = _event_timestamp(event, float(index))
        route = _event_route(event)
        identifier = _event_identifier(event)
        observed_allowed = _event_allowed(event)
        active_rule = _route_rule(active_config, route, identifier)
        proposed_rule = _route_rule(proposed_config, route, identifier)
        if not active_rule or not proposed_rule:
            continue

        key = (route, identifier)
        active_bucket = active_buckets.setdefault(key, ReplayBucket(active_rule, timestamp))
        proposed_bucket = proposed_buckets.setdefault(key, ReplayBucket(proposed_rule, timestamp))
        active_allowed = active_bucket.allow(timestamp)
        proposed_allowed = proposed_bucket.allow(timestamp)
        route_row = row(route_rows, route, "route")
        identifier_row = row(identifier_rows, identifier, "identifier")

        for target in (route_row, identifier_row):
            target["events"] += 1
            if not observed_allowed:
                target["observed_denied"] += 1
            if not active_allowed:
                target["active_replay_denied"] += 1
            if not proposed_allowed:
                target["proposed_replay_denied"] += 1
            if active_allowed and not proposed_allowed:
                target["newly_denied"] += 1
            if not active_allowed and proposed_allowed:
                target["newly_allowed"] += 1

        if (
            proposed_rule.sensitivity == "sensitive"
            or active_rule.sensitivity == "sensitive"
            or _field(event, "sensitivity") == "sensitive"
        ):
            sensitive_routes.add(route)

    routes = sorted(route_rows.values(), key=lambda item: (-item["events"], item["route"]))
    identifiers = sorted(
        identifier_rows.values(),
        key=lambda item: (-item["newly_denied"], -item["events"], item["identifier"]),
    )
    summary = {
        "events_replayed": sum(item["events"] for item in routes),
        "routes_analyzed": len(routes),
        "identifiers_analyzed": len(identifiers),
        "observed_denied": sum(item["observed_denied"] for item in routes),
        "active_replay_denied": sum(item["active_replay_denied"] for item in routes),
        "proposed_replay_denied": sum(item["proposed_replay_denied"] for item in routes),
        "newly_denied": sum(item["newly_denied"] for item in routes),
        "newly_allowed": sum(item["newly_allowed"] for item in routes),
        "sensitive_routes_impacted": sorted(
            route
            for route in sensitive_routes
            if route_rows.get(route, {}).get("newly_denied", 0) > 0
            or route_rows.get(route, {}).get("newly_allowed", 0) > 0
        ),
    }
    return {
        "mode": "recent_events_replay",
        "summary": summary,
        "routes": routes,
        "identifiers": identifiers[:20],
    }

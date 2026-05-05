import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.ai.telemetry import RateLimitEvent
from app.models.rules import RateLimitConfig, RateLimitRule

# A fallback default rule if nothing matches (e.g., 10 req / sec)
DEFAULT_RULE = RateLimitRule(rate=10.0, capacity=10)


class RulesLoadError(ValueError):
    pass


class RulesManager:
    def __init__(self, config_path: str = "rules.json"):
        self.config_path = config_path
        self.config: RateLimitConfig | None = None
        self.loaded_at: int | None = None
        config = self.load_rules()
        self._ensure_history(config)

    @property
    def history_path(self) -> Path:
        return Path(f"{self.config_path}.history.json")

    def _read_rules_file(self) -> dict[str, Any]:
        try:
            with open(self.config_path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError as exc:
            raise RulesLoadError(f"Rules file not found: {self.config_path}") from exc
        except json.JSONDecodeError as exc:
            raise RulesLoadError(f"Rules file is not valid JSON: {self.config_path}") from exc

    def _apply_config(self, config: RateLimitConfig) -> RateLimitConfig:
        self.config = config
        self.loaded_at = int(time.time())
        return config

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        try:
            os.replace(temp_path, path)
        except PermissionError:
            # Some Windows test/dev folders disallow atomic replacement over an
            # existing file. Validation has already passed, so fall back to a
            # remove-then-rename while preserving the active in-memory config
            # until the disk swap succeeds.
            path.unlink(missing_ok=True)
            os.replace(temp_path, path)

    def load_rules(self) -> RateLimitConfig:
        try:
            data = self._read_rules_file()
            return self._apply_config(self.validate_rules(data))
        except (RulesLoadError, ValidationError):
            # In case of missing/invalid file, fallback to empty rules map
            return self._apply_config(RateLimitConfig(routes={}))

    def snapshot(self) -> dict[str, Any]:
        config = self.config or RateLimitConfig(routes={})
        return {
            "loaded_at": self.loaded_at,
            "version": self.current_version(),
            "rules": config.model_dump(mode="json"),
        }

    def validate_rules(self, data: dict[str, Any]) -> RateLimitConfig:
        return RateLimitConfig.model_validate(data)

    def dry_run(
        self,
        data: dict[str, Any],
        events: list[RateLimitEvent],
        window_seconds: int,
    ) -> dict[str, Any]:
        proposed_config = self.validate_rules(data)
        active_config = self.config or RateLimitConfig(routes={})
        route_names = sorted(set(active_config.routes) | set(proposed_config.routes))

        routes = []
        estimated_additional_denials = 0
        estimated_denials = 0
        current_denials = 0

        for route_path in route_names:
            proposed_limits = proposed_config.routes.get(route_path)
            active_limits = active_config.routes.get(route_path)
            proposed_rule = proposed_limits.global_limit if proposed_limits else DEFAULT_RULE
            active_rule = active_limits.global_limit if active_limits else DEFAULT_RULE
            route_events = [event for event in events if event.route_path == route_path]
            request_count = len(route_events)
            current_limited = sum(1 for event in route_events if not event.allowed)
            estimated_allowed = min(
                request_count,
                int(proposed_rule.capacity + (proposed_rule.rate * window_seconds)),
            )
            route_estimated_denials = max(0, request_count - estimated_allowed)
            route_additional_denials = max(0, route_estimated_denials - current_limited)

            current_denials += current_limited
            estimated_denials += route_estimated_denials
            estimated_additional_denials += route_additional_denials

            routes.append({
                "route": route_path,
                "observed_requests": request_count,
                "current_denials": current_limited,
                "estimated_denials": route_estimated_denials,
                "estimated_additional_denials": route_additional_denials,
                "current_rule": active_rule.model_dump(mode="json"),
                "proposed_rule": proposed_rule.model_dump(mode="json"),
                "rate_delta": round(proposed_rule.rate - active_rule.rate, 6),
                "capacity_delta": proposed_rule.capacity - active_rule.capacity,
                "fail_mode_changed": proposed_rule.fail_mode != active_rule.fail_mode,
                "override_changes": self._describe_override_changes(active_limits, proposed_limits),
            })

        return {
            "valid": True,
            "applied": False,
            "window_seconds": window_seconds,
            "events_analyzed": len(events),
            "summary": {
                "routes_analyzed": len(routes),
                "current_denials": current_denials,
                "estimated_denials": estimated_denials,
                "estimated_additional_denials": estimated_additional_denials,
            },
            "routes": routes,
        }

    def _describe_override_changes(self, active_limits, proposed_limits) -> dict[str, list[str]]:
        active_overrides = (
            active_limits.overrides if active_limits and active_limits.overrides else {}
        )
        proposed_overrides = (
            proposed_limits.overrides if proposed_limits and proposed_limits.overrides else {}
        )
        active_keys = set(active_overrides)
        proposed_keys = set(proposed_overrides)

        changed = [
            key
            for key in sorted(active_keys & proposed_keys)
            if active_overrides[key] != proposed_overrides[key]
        ]
        return {
            "added": sorted(proposed_keys - active_keys),
            "removed": sorted(active_keys - proposed_keys),
            "changed": changed,
        }

    def update_rules(
        self,
        data: dict[str, Any],
        audit: dict[str, Any] | None = None,
    ) -> RateLimitConfig:
        new_config = self.validate_rules(data)
        config_path = Path(self.config_path)
        serialized = new_config.model_dump(mode="json")

        self._atomic_write_json(config_path, serialized)
        self._append_history(new_config, action="update", audit=audit)
        return self._apply_config(new_config)

    def _read_history(self) -> list[dict[str, Any]]:
        try:
            with open(self.history_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

        versions = data.get("versions", [])
        if not isinstance(versions, list):
            return []

        return [
            self._normalize_history_entry(version)
            for version in versions
            if isinstance(version, dict)
        ]

    def _normalize_history_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        action = str(entry.get("action") or "unknown")
        return {
            **entry,
            "rolled_back_from": entry.get("rolled_back_from"),
            "audit": self._normalize_audit(entry.get("audit"), action=action),
        }

    def _write_history(self, versions: list[dict[str, Any]]) -> None:
        self._atomic_write_json(self.history_path, {"versions": versions})

    def _ensure_history(self, config: RateLimitConfig) -> None:
        if self._read_history():
            return

        self._append_history(config, action="initial")

    def _append_history(
        self,
        config: RateLimitConfig,
        *,
        action: str,
        rolled_back_from: int | None = None,
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        versions = self._read_history()
        version = max((item.get("version", 0) for item in versions), default=0) + 1
        entry = {
            "version": version,
            "created_at": int(time.time()),
            "action": action,
            "rolled_back_from": rolled_back_from,
            "audit": self._normalize_audit(audit, action=action),
            "rules": config.model_dump(mode="json"),
        }
        versions.append(entry)
        self._write_history(versions)
        return entry

    def _normalize_audit(
        self,
        audit: dict[str, Any] | None,
        *,
        action: str,
    ) -> dict[str, Any]:
        audit = audit or {}

        def clean(value: Any, default: str | None = None, max_length: int = 240) -> str | None:
            if value is None:
                return default
            text = str(value).strip()
            if not text:
                return default
            return text[:max_length]

        return {
            "actor": clean(audit.get("actor"), default="system", max_length=120),
            "source": clean(audit.get("source"), default=f"rules-manager:{action}", max_length=120),
            "reason": clean(audit.get("reason"), max_length=500),
            "request_id": clean(audit.get("request_id"), max_length=120),
            "client_host": clean(audit.get("client_host"), max_length=120),
        }

    def history(self) -> dict[str, Any]:
        versions = self._read_history()
        return {
            "current_version": self.current_version(),
            "versions": versions,
        }

    def current_version(self) -> int | None:
        versions = self._read_history()
        if not versions:
            return None

        return max(item.get("version", 0) for item in versions)

    def rollback(self, version: int, audit: dict[str, Any] | None = None) -> RateLimitConfig:
        versions = self._read_history()
        target = next((item for item in versions if item.get("version") == version), None)
        if not target:
            raise RulesLoadError(f"Rule version not found: {version}")

        new_config = self.validate_rules(target["rules"])
        self._atomic_write_json(Path(self.config_path), new_config.model_dump(mode="json"))
        self._append_history(
            new_config,
            action="rollback",
            rolled_back_from=version,
            audit=audit,
        )
        return self._apply_config(new_config)

    def get_rule(self, route_path: str, identifier: str) -> RateLimitRule:
        """
        Get the specific rule for a route and an identifier.
        """
        if not self.config or route_path not in self.config.routes:
            return DEFAULT_RULE
            
        route_limits = self.config.routes[route_path]
        
        if route_limits.overrides and identifier in route_limits.overrides:
            return route_limits.overrides[identifier]
            
        return route_limits.global_limit

    def refresh(self, audit: dict[str, Any] | None = None) -> RateLimitConfig:
        """
        Reload the rules configuration without discarding active rules on failure.
        """
        data = self._read_rules_file()
        config = self.validate_rules(data)
        self._append_history(config, action="reload", audit=audit)
        return self._apply_config(config)

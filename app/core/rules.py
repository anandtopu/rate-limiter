import json
import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.ai.simulation import replay_policy
from app.ai.telemetry import RateLimitEvent
from app.models.rules import RateLimitConfig, RateLimitRule

# A fallback default rule if nothing matches (e.g., 10 req / sec)
DEFAULT_RULE = RateLimitRule(rate=10.0, capacity=10)
RULE_EXPORT_KIND = "rate-limiter.rules.export"
RULE_EXPORT_SCHEMA_VERSION = 1


class RulesLoadError(ValueError):
    pass


class RulesApprovalError(ValueError):
    pass


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
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


class JsonRuleStore:
    backend = "json"

    def __init__(self, config_path: str = "rules.json"):
        self.config_path = Path(config_path)

    @property
    def history_path(self) -> Path:
        return Path(f"{self.config_path}.history.json")

    @property
    def pending_path(self) -> Path:
        return Path(f"{self.config_path}.pending.json")

    def read_rules(self) -> dict[str, Any]:
        try:
            with open(self.config_path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError as exc:
            raise RulesLoadError(f"Rules file not found: {self.config_path}") from exc
        except json.JSONDecodeError as exc:
            raise RulesLoadError(f"Rules file is not valid JSON: {self.config_path}") from exc

    def write_rules(self, data: dict[str, Any]) -> None:
        atomic_write_json(self.config_path, data)

    def read_history(self) -> list[dict[str, Any]]:
        try:
            with open(self.history_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

        versions = data.get("versions", [])
        return versions if isinstance(versions, list) else []

    def write_history(self, versions: list[dict[str, Any]]) -> None:
        atomic_write_json(self.history_path, {"versions": versions})

    def read_pending(self) -> list[dict[str, Any]]:
        try:
            with open(self.pending_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

        requests = data.get("requests", [])
        return requests if isinstance(requests, list) else []

    def write_pending(self, requests: list[dict[str, Any]]) -> None:
        atomic_write_json(self.pending_path, {"requests": requests})


class SQLiteRuleStore:
    backend = "sqlite"

    def __init__(self, db_path: str = "data/rules.sqlite3", seed_config_path: str = "rules.json"):
        self.db_path = Path(db_path)
        self.seed_config_path = Path(seed_config_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rule_store (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )

    def _read_document(self, name: str) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM rule_store WHERE name = ?",
                (name,),
            ).fetchone()

        if not row:
            return None

        try:
            return json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise RulesLoadError(f"Stored rule document is not valid JSON: {name}") from exc

    def _write_document(self, name: str, payload: Any) -> None:
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rule_store (name, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (name, serialized, int(time.time())),
            )

    def read_rules(self) -> dict[str, Any]:
        data = self._read_document("rules")
        if isinstance(data, dict):
            return data

        try:
            with open(self.seed_config_path, encoding="utf-8") as f:
                seeded_data = json.load(f)
        except FileNotFoundError as exc:
            raise RulesLoadError(f"Rules file not found: {self.seed_config_path}") from exc
        except json.JSONDecodeError as exc:
            raise RulesLoadError(
                f"Rules file is not valid JSON: {self.seed_config_path}"
            ) from exc

        self.write_rules(seeded_data)
        return seeded_data

    def write_rules(self, data: dict[str, Any]) -> None:
        self._write_document("rules", data)

    def read_history(self) -> list[dict[str, Any]]:
        data = self._read_document("history")
        if not isinstance(data, dict):
            return []

        versions = data.get("versions", [])
        return versions if isinstance(versions, list) else []

    def write_history(self, versions: list[dict[str, Any]]) -> None:
        self._write_document("history", {"versions": versions})

    def read_pending(self) -> list[dict[str, Any]]:
        data = self._read_document("pending")
        if not isinstance(data, dict):
            return []

        requests = data.get("requests", [])
        return requests if isinstance(requests, list) else []

    def write_pending(self, requests: list[dict[str, Any]]) -> None:
        self._write_document("pending", {"requests": requests})


class RulesManager:
    def __init__(self, config_path: str = "rules.json", store: Any | None = None):
        self.config_path = config_path
        self.store = store or JsonRuleStore(config_path)
        self.config: RateLimitConfig | None = None
        self.loaded_at: int | None = None
        config = self.load_rules()
        self._ensure_history(config)

    @property
    def history_path(self) -> Path:
        return getattr(self.store, "history_path", Path(f"{self.config_path}.history.json"))

    @property
    def pending_path(self) -> Path:
        return getattr(self.store, "pending_path", Path(f"{self.config_path}.pending.json"))

    def _read_rules_file(self) -> dict[str, Any]:
        return self.store.read_rules()

    def _apply_config(self, config: RateLimitConfig) -> RateLimitConfig:
        self.config = config
        self.loaded_at = int(time.time())
        return config

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        atomic_write_json(path, data)

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
            "store": self.store.backend,
            "rules": config.model_dump(mode="json"),
        }

    def export_rules(self) -> dict[str, Any]:
        config = self.config or RateLimitConfig(routes={})
        return {
            "kind": RULE_EXPORT_KIND,
            "schema_version": RULE_EXPORT_SCHEMA_VERSION,
            "exported_at": int(time.time()),
            "version": self.current_version(),
            "store": self.store.backend,
            "rules": config.model_dump(mode="json"),
        }

    def import_payload_rules(self, data: dict[str, Any]) -> dict[str, Any]:
        if "rules" not in data:
            return data

        rules = data["rules"]
        if not isinstance(rules, dict):
            raise RulesLoadError("Imported rules payload must include a rules object")

        return rules

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

        report = {
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
        report["replay"] = replay_policy(
            active_config=active_config,
            proposed_config=proposed_config,
            events=events,
        )
        return report

    def draft_from_recommendations(self, recommendations: dict[str, Any]) -> dict[str, Any]:
        active_config = self.config or RateLimitConfig(routes={})
        proposed_config = active_config.model_copy(deep=True)
        changes: list[dict[str, Any]] = []

        for item in recommendations.get("items", []):
            recommendation_type = item.get("type")
            action = (item.get("recommendation") or {}).get("action")
            proposed_change = item.get("proposed_change") or {}

            if proposed_change.get("kind") == "scale_route_limit":
                change = self._apply_tuning_recommendation(proposed_config, item)
                if change:
                    changes.append(change)
            elif proposed_change.get("kind") == "set_fail_mode":
                change = self._apply_fail_mode_recommendation(proposed_config, item)
                if change:
                    changes.append(change)
            elif proposed_change.get("kind") == "set_algorithm":
                change = self._apply_algorithm_recommendation(proposed_config, item)
                if change:
                    changes.append(change)
            elif proposed_change.get("kind") == "add_identifier_override":
                change = self._apply_identifier_override_recommendation(proposed_config, item)
                if change:
                    changes.append(change)
            elif recommendation_type == "tuning" and action == "review_limits":
                change = self._apply_tuning_recommendation(proposed_config, item)
                if change:
                    changes.append(change)
            elif recommendation_type == "reliability" and action == "investigate_redis":
                changes.extend(self._apply_reliability_recommendation(proposed_config))

        return {
            "valid": True,
            "applied": False,
            "generated_at": recommendations.get("generated_at"),
            "recommendations": recommendations,
            "changes": changes,
            "rules": proposed_config.model_dump(mode="json"),
        }

    def _apply_tuning_recommendation(
        self,
        proposed_config: RateLimitConfig,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        route = item.get("route")
        if route not in proposed_config.routes:
            return None

        route_limits = proposed_config.routes[route]
        rule = route_limits.global_limit
        proposed_change = item.get("proposed_change") or {}
        signal = item.get("signal") or {}
        limited_ratio = float(signal.get("rate_limited_ratio") or 0)
        multiplier = float(
            proposed_change.get("rate_multiplier")
            or proposed_change.get("capacity_multiplier")
            or (2.0 if limited_ratio >= 0.3 else 1.5)
        )
        capacity_multiplier = float(proposed_change.get("capacity_multiplier") or multiplier)
        min_increment = int(proposed_change.get("min_capacity_increment") or 1)

        before = rule.model_dump(mode="json")
        rule.rate = round(rule.rate * multiplier, 6)
        rule.capacity = max(
            rule.capacity + min_increment,
            math.ceil(rule.capacity * capacity_multiplier),
        )
        after = rule.model_dump(mode="json")

        return {
            "type": "tuning",
            "route": route,
            "reason": item.get("rationale") or "High rate-limit ratio recommendation",
            "before": before,
            "after": after,
        }

    def _apply_fail_mode_recommendation(
        self,
        proposed_config: RateLimitConfig,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        proposed_change = item.get("proposed_change") or {}
        route = proposed_change.get("route") or item.get("route")
        if route not in proposed_config.routes:
            return None

        fail_mode = proposed_change.get("fail_mode")
        if fail_mode not in {"open", "closed"}:
            return None

        rule = proposed_config.routes[route].global_limit
        if rule.fail_mode == fail_mode:
            return None

        before = rule.model_dump(mode="json")
        rule.fail_mode = fail_mode
        return {
            "type": item.get("type") or "reliability",
            "route": route,
            "reason": item.get("rationale") or "Fail-mode recommendation",
            "before": before,
            "after": rule.model_dump(mode="json"),
        }

    def _apply_algorithm_recommendation(
        self,
        proposed_config: RateLimitConfig,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        proposed_change = item.get("proposed_change") or {}
        route = proposed_change.get("route") or item.get("route")
        if route not in proposed_config.routes:
            return None

        algorithm = proposed_change.get("algorithm")
        if algorithm not in {"token_bucket", "fixed_window", "sliding_window"}:
            return None

        rule = proposed_config.routes[route].global_limit
        if rule.algorithm == algorithm:
            return None

        before = rule.model_dump(mode="json")
        rule.algorithm = algorithm
        return {
            "type": item.get("type") or "algorithm",
            "route": route,
            "reason": item.get("rationale") or "Algorithm recommendation",
            "before": before,
            "after": rule.model_dump(mode="json"),
        }

    def _apply_identifier_override_recommendation(
        self,
        proposed_config: RateLimitConfig,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        proposed_change = item.get("proposed_change") or {}
        route = proposed_change.get("route") or item.get("route")
        identifier = proposed_change.get("identifier") or (item.get("signal") or {}).get(
            "identifier"
        )
        if route not in proposed_config.routes or not identifier:
            return None

        route_limits = proposed_config.routes[route]
        source_rule = route_limits.global_limit
        before = source_rule.model_dump(mode="json")
        override_rule = source_rule.model_copy(deep=True)
        rate_multiplier = float(proposed_change.get("rate_multiplier") or 0.5)
        capacity_multiplier = float(proposed_change.get("capacity_multiplier") or 0.5)
        override_rule.rate = max(0.001, round(source_rule.rate * rate_multiplier, 6))
        override_rule.capacity = max(1, math.ceil(source_rule.capacity * capacity_multiplier))
        overrides = dict(route_limits.overrides or {})
        previous_override = overrides.get(identifier)
        overrides[str(identifier)] = override_rule
        route_limits.overrides = overrides

        return {
            "type": item.get("type") or "abuse",
            "route": route,
            "identifier": str(identifier),
            "reason": item.get("rationale") or "Identifier override recommendation",
            "before": previous_override.model_dump(mode="json") if previous_override else before,
            "after": override_rule.model_dump(mode="json"),
        }

    def _apply_reliability_recommendation(
        self,
        proposed_config: RateLimitConfig,
    ) -> list[dict[str, Any]]:
        changes = []
        for route, route_limits in proposed_config.routes.items():
            if not self._route_has_sensitive_rule(route_limits):
                continue

            rule = route_limits.global_limit
            if rule.fail_mode == "closed":
                continue

            before = rule.model_dump(mode="json")
            rule.fail_mode = "closed"
            changes.append({
                "type": "reliability",
                "route": route,
                "reason": "Sensitive route fail-open recommendation",
                "before": before,
                "after": rule.model_dump(mode="json"),
            })

        return changes

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
        return self.apply_rules(new_config, action="update", audit=audit)

    def apply_rules(
        self,
        new_config: RateLimitConfig,
        *,
        action: str,
        audit: dict[str, Any] | None = None,
    ) -> RateLimitConfig:
        serialized = new_config.model_dump(mode="json")

        self.store.write_rules(serialized)
        self._append_history(new_config, action=action, audit=audit)
        return self._apply_config(new_config)

    def sensitive_routes_touched(self, proposed_config: RateLimitConfig) -> list[str]:
        active_config = self.config or RateLimitConfig(routes={})
        route_names = sorted(set(active_config.routes) | set(proposed_config.routes))

        sensitive_routes = []
        for route_path in route_names:
            active_limits = active_config.routes.get(route_path)
            proposed_limits = proposed_config.routes.get(route_path)
            if not (
                self._route_has_sensitive_rule(active_limits)
                or self._route_has_sensitive_rule(proposed_limits)
            ):
                continue

            active_data = active_limits.model_dump(mode="json") if active_limits else None
            proposed_data = proposed_limits.model_dump(mode="json") if proposed_limits else None
            if active_data != proposed_data:
                sensitive_routes.append(route_path)

        return sensitive_routes

    def _route_has_sensitive_rule(self, route_limits) -> bool:
        if not route_limits:
            return False

        if route_limits.global_limit.sensitivity == "sensitive":
            return True

        overrides = route_limits.overrides or {}
        return any(rule.sensitivity == "sensitive" for rule in overrides.values())

    def _read_pending_requests(self) -> list[dict[str, Any]]:
        return [
            self._normalize_pending_request(item)
            for item in self.store.read_pending()
            if isinstance(item, dict)
        ]

    def _normalize_pending_request(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            **item,
            "id": str(item.get("id") or ""),
            "status": str(item.get("status") or "pending"),
            "base_version": item.get("base_version"),
            "sensitive_routes": [
                str(route) for route in item.get("sensitive_routes", []) if route
            ],
            "audit": self._normalize_audit(item.get("audit"), action="request_sensitive_update"),
            "approval_audit": (
                self._normalize_audit(
                    item.get("approval_audit"),
                    action="approve_sensitive_update",
                )
                if item.get("approval_audit")
                else None
            ),
            "rejection_audit": (
                self._normalize_audit(
                    item.get("rejection_audit"),
                    action="reject_sensitive_update",
                )
                if item.get("rejection_audit")
                else None
            ),
        }

    def _write_pending_requests(self, requests: list[dict[str, Any]]) -> None:
        self.store.write_pending(requests)

    def request_sensitive_update(
        self,
        config: RateLimitConfig,
        *,
        sensitive_routes: list[str],
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "id": uuid4().hex,
            "status": "pending",
            "created_at": int(time.time()),
            "base_version": self.current_version(),
            "sensitive_routes": sensitive_routes,
            "audit": self._normalize_audit(audit, action="request_sensitive_update"),
            "rules": config.model_dump(mode="json"),
        }
        requests = self._read_pending_requests()
        requests.append(entry)
        self._write_pending_requests(requests)
        return entry

    def pending_updates(self, *, include_resolved: bool = False) -> dict[str, Any]:
        requests = self._read_pending_requests()
        if not include_resolved:
            requests = [item for item in requests if item.get("status") == "pending"]

        return {"requests": requests}

    def approve_pending_update(
        self,
        request_id: str,
        audit: dict[str, Any] | None = None,
    ) -> tuple[RateLimitConfig, dict[str, Any]]:
        requests = self._read_pending_requests()
        pending_request = self._find_pending_request(requests, request_id)
        approval_audit = self._normalize_audit(audit, action="approve_sensitive_update")

        proposer = pending_request["audit"]["actor"]
        approver = approval_audit["actor"]
        if proposer == approver:
            raise RulesApprovalError("Sensitive rule changes require approval by a second admin")

        base_version = pending_request.get("base_version")
        if base_version != self.current_version():
            raise RulesApprovalError(
                "Pending rule change is stale because the active rule version changed"
            )

        config = self.validate_rules(pending_request["rules"])
        self.apply_rules(config, action="approve_sensitive_update", audit=approval_audit)

        pending_request["status"] = "approved"
        pending_request["approved_at"] = int(time.time())
        pending_request["approval_audit"] = approval_audit
        pending_request["applied_version"] = self.current_version()
        self._write_pending_requests(requests)
        return config, pending_request

    def reject_pending_update(
        self,
        request_id: str,
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requests = self._read_pending_requests()
        pending_request = self._find_pending_request(requests, request_id)
        pending_request["status"] = "rejected"
        pending_request["rejected_at"] = int(time.time())
        pending_request["rejection_audit"] = self._normalize_audit(
            audit,
            action="reject_sensitive_update",
        )
        self._write_pending_requests(requests)
        return pending_request

    def _find_pending_request(
        self,
        requests: list[dict[str, Any]],
        request_id: str,
    ) -> dict[str, Any]:
        pending_request = next(
            (
                item
                for item in requests
                if item.get("id") == request_id and item.get("status") == "pending"
            ),
            None,
        )
        if not pending_request:
            raise RulesApprovalError(f"Pending rule change not found: {request_id}")

        return pending_request

    def _read_history(self) -> list[dict[str, Any]]:
        return [
            self._normalize_history_entry(version)
            for version in self.store.read_history()
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
        self.store.write_history(versions)

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

    def audit_log(
        self,
        *,
        route: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        sensitivity: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        rows = self._audit_rows()
        filtered = [
            row
            for row in rows
            if self._audit_row_matches(
                row,
                route=route,
                actor=actor,
                action=action,
                sensitivity=sensitivity,
                since=since,
                until=until,
            )
        ]
        filtered = filtered[-limit:]

        return {
            "filters": {
                "route": route,
                "actor": actor,
                "action": action,
                "sensitivity": sensitivity,
                "since": since,
                "until": until,
                "limit": limit,
            },
            "count": len(filtered),
            "entries": list(reversed(filtered)),
        }

    def _audit_rows(self) -> list[dict[str, Any]]:
        rows = []
        previous_rules: dict[str, Any] | None = None

        for entry in self._read_history():
            current_rules = entry.get("rules") if isinstance(entry.get("rules"), dict) else {}
            changed_routes = self._changed_route_rows(previous_rules, current_rules)
            rows.append({
                "version": entry.get("version"),
                "created_at": entry.get("created_at"),
                "action": entry.get("action"),
                "rolled_back_from": entry.get("rolled_back_from"),
                "audit": entry.get("audit") or {},
                "changed_routes": changed_routes,
            })
            previous_rules = current_rules

        return rows

    def _changed_route_rows(
        self,
        previous_rules: dict[str, Any] | None,
        current_rules: dict[str, Any],
    ) -> list[dict[str, Any]]:
        previous_routes = (previous_rules or {}).get("routes", {})
        current_routes = current_rules.get("routes", {})
        if not isinstance(previous_routes, dict):
            previous_routes = {}
        if not isinstance(current_routes, dict):
            current_routes = {}

        route_names = sorted(set(previous_routes) | set(current_routes))
        changed = []
        for route_path in route_names:
            previous_route = previous_routes.get(route_path)
            current_route = current_routes.get(route_path)
            if previous_route == current_route:
                continue

            if previous_route is None:
                change = "added"
                sensitivity_source = current_route
            elif current_route is None:
                change = "removed"
                sensitivity_source = previous_route
            else:
                change = "changed"
                sensitivity_source = current_route

            changed.append({
                "route": route_path,
                "change": change,
                "sensitivity": self._route_sensitivity_label(sensitivity_source),
            })

        return changed

    def _route_sensitivity_label(self, route_data: Any) -> str | None:
        if not isinstance(route_data, dict):
            return None

        global_limit = route_data.get("global_limit")
        if isinstance(global_limit, dict) and global_limit.get("sensitivity"):
            return str(global_limit["sensitivity"])

        overrides = route_data.get("overrides") or {}
        if isinstance(overrides, dict):
            labels = sorted(
                {
                    str(rule["sensitivity"])
                    for rule in overrides.values()
                    if isinstance(rule, dict) and rule.get("sensitivity")
                }
            )
            if labels:
                return "sensitive" if "sensitive" in labels else labels[-1]

        return None

    def _audit_row_matches(
        self,
        row: dict[str, Any],
        *,
        route: str | None,
        actor: str | None,
        action: str | None,
        sensitivity: str | None,
        since: float | None,
        until: float | None,
    ) -> bool:
        if since is not None and (row.get("created_at") or 0) < since:
            return False

        if until is not None and (row.get("created_at") or 0) > until:
            return False

        if action and str(row.get("action") or "").lower() != action.lower():
            return False

        audit = row.get("audit") or {}
        if actor and actor.lower() not in str(audit.get("actor") or "").lower():
            return False

        changed_routes = row.get("changed_routes") or []
        if route and not any(
            route.lower() in str(item.get("route") or "").lower() for item in changed_routes
        ):
            return False

        if sensitivity and not any(
            str(item.get("sensitivity") or "").lower() == sensitivity.lower()
            for item in changed_routes
        ):
            return False

        return True

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
        self.store.write_rules(new_config.model_dump(mode="json"))
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

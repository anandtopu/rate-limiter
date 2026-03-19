import json
from typing import Optional
from app.models.rules import RateLimitConfig, RateLimitRule, RouteLimits

# A fallback default rule if nothing matches (e.g., 10 req / sec)
DEFAULT_RULE = RateLimitRule(rate=10.0, capacity=10)

class RulesManager:
    def __init__(self, config_path: str = "rules.json"):
        self.config_path = config_path
        self.config: Optional[RateLimitConfig] = None
        self.load_rules()

    def load_rules(self):
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
                self.config = RateLimitConfig(**data)
        except (FileNotFoundError, json.JSONDecodeError):
            # In case of missing/invalid file, fallback to empty rules map
            self.config = RateLimitConfig(routes={})

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

    def refresh(self):
        """
        Reload the rules configuration.
        """
        self.load_rules()

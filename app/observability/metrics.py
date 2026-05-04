from collections import Counter
from collections.abc import Iterable
from threading import Lock


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
        self._lock = Lock()

    def increment(self, name: str, **labels: str) -> None:
        label_tuple = tuple(sorted((key, str(value)) for key, value in labels.items()))
        with self._lock:
            self._counters[(name, label_tuple)] += 1

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            items = sorted(self._counters.items())

        for (name, labels), value in items:
            lines.append(f"{name}{_format_labels(labels)} {value}")

        return "\n".join(lines) + ("\n" if lines else "")

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()


def _format_labels(labels: Iterable[tuple[str, str]]) -> str:
    label_parts = [f'{key}="{_escape_label(value)}"' for key, value in labels]
    return "{" + ",".join(label_parts) + "}" if label_parts else ""


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


metrics_registry = MetricsRegistry()


def record_rate_limit_metric(
    *,
    route_path: str,
    allowed: bool,
    redis_failed: bool,
    redis_fail_open: bool,
) -> None:
    decision = "allowed" if allowed else "denied"
    metric_name = (
        "rate_limiter_allowed_requests_total"
        if allowed
        else "rate_limiter_denied_requests_total"
    )
    metrics_registry.increment(metric_name, route=route_path, decision=decision)

    if redis_fail_open:
        metrics_registry.increment("rate_limiter_redis_fail_open_total", route=route_path)
    elif redis_failed:
        metrics_registry.increment("rate_limiter_redis_fail_closed_total", route=route_path)


def record_rule_reload_metric(*, status: str) -> None:
    metrics_registry.increment("rate_limiter_rule_reloads_total", status=status)

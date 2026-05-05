from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any


def _field(event: Any, name: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


def _denial_ratio(denied: int, requests: int) -> float:
    if requests <= 0:
        return 0.0
    return round(denied / requests, 4)


def _top_identifier_concentration(identifier_counts: Counter[str], requests: int) -> float:
    if requests <= 0 or not identifier_counts:
        return 0.0
    return round(identifier_counts.most_common(1)[0][1] / requests, 4)


def _sorted_labels(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in {None, ""}})


def build_route_features(events: Iterable[Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        grouped[str(_field(event, "route_path", "unknown"))].append(event)

    features = []
    for route, route_events in grouped.items():
        requests = len(route_events)
        denied = sum(1 for event in route_events if not bool(_field(event, "allowed", False)))
        redis_fail_open = sum(
            1 for event in route_events if bool(_field(event, "redis_fail_open", False))
        )
        identifiers = Counter(str(_field(event, "identifier", "unknown")) for event in route_events)
        retry_after_values = [
            int(value)
            for event in route_events
            if (value := _field(event, "retry_after_s")) is not None
        ]

        features.append({
            "route": route,
            "requests": requests,
            "denied": denied,
            "denial_ratio": _denial_ratio(denied, requests),
            "unique_identifiers": len(identifiers),
            "top_identifier": identifiers.most_common(1)[0][0] if identifiers else None,
            "top_identifier_requests": identifiers.most_common(1)[0][1] if identifiers else 0,
            "top_identifier_concentration": _top_identifier_concentration(
                identifiers,
                requests,
            ),
            "redis_fail_open": redis_fail_open,
            "algorithms": _sorted_labels(_field(event, "algorithm") for event in route_events),
            "fail_modes": _sorted_labels(_field(event, "fail_mode") for event in route_events),
            "tiers": _sorted_labels(_field(event, "tier") for event in route_events),
            "owners": _sorted_labels(_field(event, "owner") for event in route_events),
            "sensitivities": _sorted_labels(
                _field(event, "sensitivity") for event in route_events
            ),
            "methods": _sorted_labels(_field(event, "method") for event in route_events),
            "status_codes": sorted(
                {
                    int(status_code)
                    for event in route_events
                    if (status_code := _field(event, "status_code")) is not None
                }
            ),
            "max_retry_after_s": max(retry_after_values) if retry_after_values else None,
            "latest_rule_version": max(
                (
                    int(version)
                    for event in route_events
                    if (version := _field(event, "rule_version")) is not None
                ),
                default=None,
            ),
        })

    return sorted(features, key=lambda item: (-item["requests"], item["route"]))


def build_identifier_features(events: Iterable[Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        grouped[str(_field(event, "identifier", "unknown"))].append(event)

    features = []
    for identifier, identifier_events in grouped.items():
        requests = len(identifier_events)
        denied = sum(1 for event in identifier_events if not bool(_field(event, "allowed", False)))
        routes = Counter(str(_field(event, "route_path", "unknown")) for event in identifier_events)
        features.append({
            "identifier": identifier,
            "requests": requests,
            "denied": denied,
            "denial_ratio": _denial_ratio(denied, requests),
            "unique_routes": len(routes),
            "top_route": routes.most_common(1)[0][0] if routes else None,
            "top_route_requests": routes.most_common(1)[0][1] if routes else 0,
            "redis_fail_open": sum(
                1 for event in identifier_events if bool(_field(event, "redis_fail_open", False))
            ),
        })

    return sorted(
        features,
        key=lambda item: (-item["denied"], -item["requests"], item["identifier"]),
    )


def build_route_identifier_features(events: Iterable[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for event in events:
        key = (
            str(_field(event, "route_path", "unknown")),
            str(_field(event, "identifier", "unknown")),
        )
        grouped[key].append(event)

    features = []
    for (route, identifier), pair_events in grouped.items():
        requests = len(pair_events)
        denied = sum(1 for event in pair_events if not bool(_field(event, "allowed", False)))
        features.append({
            "route": route,
            "identifier": identifier,
            "requests": requests,
            "denied": denied,
            "denial_ratio": _denial_ratio(denied, requests),
            "redis_fail_open": sum(
                1 for event in pair_events if bool(_field(event, "redis_fail_open", False))
            ),
        })

    return sorted(
        features,
        key=lambda item: (-item["denied"], -item["requests"], item["route"], item["identifier"]),
    )


def build_feature_summary(events: Iterable[Any]) -> dict[str, Any]:
    event_list = list(events)
    return {
        "events_analyzed": len(event_list),
        "routes": build_route_features(event_list),
        "identifiers": build_identifier_features(event_list),
        "route_identifiers": build_route_identifier_features(event_list),
    }

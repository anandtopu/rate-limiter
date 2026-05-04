from contextlib import nullcontext
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Status, StatusCode

_enabled = False
_configured = False


def configure_tracing(
    *,
    enabled: bool,
    service_name: str,
    console_exporter: bool,
    otlp_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
    otlp_timeout_s: float = 10.0,
) -> None:
    global _configured, _enabled

    _enabled = enabled
    if not enabled or _configured:
        return

    provider = TracerProvider(
        resource=Resource.create({
            "service.name": service_name,
        })
    )
    if console_exporter:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    if otlp_enabled:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=otlp_endpoint,
                    headers=parse_otlp_headers(otlp_headers),
                    timeout=otlp_timeout_s,
                )
            )
        )

    trace.set_tracer_provider(provider)
    _configured = True


def parse_otlp_headers(headers: str | None) -> dict[str, str] | None:
    if not headers:
        return None

    parsed = {}
    for pair in headers.split(","):
        if not pair.strip() or "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            parsed[key] = value

    return parsed or None


def start_span(name: str, attributes: dict[str, Any] | None = None):
    if not _enabled:
        return nullcontext()

    tracer = trace.get_tracer("rate_limiter")
    return tracer.start_as_current_span(name, attributes=attributes)


def set_span_attributes(attributes: dict[str, Any]) -> None:
    if not _enabled:
        return

    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_attributes(attributes)


def mark_span_error(message: str) -> None:
    if not _enabled:
        return

    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_status(Status(StatusCode.ERROR, message))


def current_trace_id() -> str | None:
    if not _enabled:
        return None

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None

    return f"{span_context.trace_id:032x}"

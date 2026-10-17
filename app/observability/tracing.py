"""OpenTelemetry distributed tracing setup and context propagation.

Connects HTTP API requests, LangGraph investigation nodes, and evidence queries
into unified distributed traces exportable via OTLP (e.g. Jaeger or OTel collector).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request, Response
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Span, SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.middleware.base import BaseHTTPMiddleware

from app.observability.context import (
    request_id_var,
    span_id_var,
    trace_id_var,
)

logger = logging.getLogger(__name__)

_TRACER_PROVIDER: TracerProvider | None = None
_PROPAGATOR = TraceContextTextMapPropagator()


def init_tracing(
    endpoint: str | None = None,
    service_name: str = "nexops",
    debug_console: bool = False,
) -> TracerProvider:
    """Initialize OpenTelemetry TracerProvider with optional OTLP HTTP exporter."""
    global _TRACER_PROVIDER

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # If OTLP endpoint configured, attempt to wire OTLP HTTP exporter
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            # Ensure endpoint has /v1/traces suffix if base url supplied
            otlp_url = (
                endpoint if endpoint.endswith("/v1/traces") else f"{endpoint.rstrip('/')}/v1/traces"
            )
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_url)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info("OTLP trace exporter configured for endpoint: %s", otlp_url)
        except Exception as exc:
            logger.warning("Could not initialize OTLP trace exporter: %s", exc)

    if debug_console:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _TRACER_PROVIDER = provider
    return provider


def shutdown_tracing() -> None:
    """Flush and shut down tracing provider cleanly."""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER:
        try:
            _TRACER_PROVIDER.shutdown()
        except Exception as exc:
            logger.warning("Error shutting down tracer provider: %s", exc)
        _TRACER_PROVIDER = None


def get_tracer(name: str = "nexops") -> trace.Tracer:
    """Retrieve the configured tracer instance."""
    return trace.get_tracer(name)


def get_current_trace_id() -> str | None:
    """Return the active trace ID as 32-character hex, or contextvar fallback."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return trace_id_var.get()


def get_current_span_id() -> str | None:
    """Return the active span ID as 16-character hex, or contextvar fallback."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        return format(ctx.span_id, "016x")
    return span_id_var.get()


@asynccontextmanager
async def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> AsyncIterator[Span]:
    """Async context manager to wrap code blocks in an OpenTelemetry span.

    Updates active context variables for log correlation and extracts formatted IDs.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=kind) as span:
        ctx = span.get_span_context()
        if ctx.is_valid:
            t_hex = format(ctx.trace_id, "032x")
            s_hex = format(ctx.span_id, "016x")
            token_t = trace_id_var.set(t_hex)
            token_s = span_id_var.set(s_hex)
        else:
            token_t = None
            token_s = None

        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    span.set_attribute(
                        k, str(v) if not isinstance(v, (bool, str, int, float)) else v
                    )

        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            raise
        finally:
            if token_t:
                trace_id_var.reset(token_t)
            if token_s:
                span_id_var.reset(token_s)


class TracingMiddleware(BaseHTTPMiddleware):
    """Starlette middleware to correlate incoming HTTP requests with distributed tracing."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        tracer = get_tracer()

        # Extract W3C headers if provided
        headers_dict = dict(request.headers)
        extracted_ctx = _PROPAGATOR.extract(carrier=headers_dict)

        # Generate or extract request_id
        req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token_req = request_id_var.set(req_id)

        route_label = request.url.path
        span_name = f"HTTP {request.method} {route_label}"

        with tracer.start_as_current_span(
            span_name,
            context=extracted_ctx,
            kind=SpanKind.SERVER,
        ) as span:
            ctx = span.get_span_context()
            trace_id_str = format(ctx.trace_id, "032x") if ctx.is_valid else uuid.uuid4().hex
            span_id_str = format(ctx.span_id, "016x") if ctx.is_valid else uuid.uuid4().hex[:16]

            token_trace = trace_id_var.set(trace_id_str)
            token_span = span_id_var.set(span_id_str)

            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.route", route_label)
            span.set_attribute("nexops.request_id", req_id)

            try:
                response: Response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 500:
                    span.set_status(StatusCode.ERROR, f"HTTP {response.status_code}")
                else:
                    span.set_status(StatusCode.OK)

                # Inject trace IDs into response headers for caller inspection
                response.headers["x-trace-id"] = trace_id_str
                response.headers["x-span-id"] = span_id_str
                response.headers["x-request-id"] = req_id
                return response
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
                raise
            finally:
                request_id_var.reset(token_req)
                trace_id_var.reset(token_trace)
                span_id_var.reset(token_span)

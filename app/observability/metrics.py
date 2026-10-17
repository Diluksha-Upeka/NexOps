"""Prometheus metrics instrumentation with cardinality protection.

Exposes application-level metrics covering:
- HTTP request counts and latency histograms with normalized route templates
- Active simulator fault scenarios
- LangGraph investigation run counts and durations
- Evidence items gathered by source type
- Remediation actions and execution status
- LLM adapter requests, durations, and fallback occurrences
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match

# ── Metric Definitions ────────────────────────────────────────────────

HTTP_REQUESTS_TOTAL = Counter(
    "nexops_http_requests_total",
    "Total HTTP requests processed by NexOps",
    ["service", "route", "method", "status_class"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "nexops_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["service", "route", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

ACTIVE_SIMULATOR_FAULTS = Gauge(
    "nexops_simulator_fault_active",
    "Currently active simulator fault scenarios (1 = active, 0 = inactive)",
    ["scenario_key"],
)

INVESTIGATION_RUNS_TOTAL = Counter(
    "nexops_investigation_runs_total",
    "LangGraph investigation runs",
    ["service", "status"],
)

INVESTIGATION_RUN_DURATION_SECONDS = Histogram(
    "nexops_investigation_run_duration_seconds",
    "LangGraph investigation duration in seconds",
    ["service", "status"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 45.0, 90.0, 180.0),
)

EVIDENCE_ITEMS_TOTAL = Counter(
    "nexops_evidence_items_total",
    "Total evidence items collected during investigations",
    ["source_type"],
)

REMEDIATION_ACTIONS_TOTAL = Counter(
    "nexops_remediation_actions_total",
    "Sandbox remediation actions executed",
    ["action_type", "status"],
)

LLM_REQUESTS_TOTAL = Counter(
    "nexops_llm_requests_total",
    "LLM adapter requests",
    ["provider", "model", "status"],
)

LLM_REQUEST_DURATION_SECONDS = Histogram(
    "nexops_llm_request_duration_seconds",
    "LLM adapter call duration in seconds",
    ["provider", "model"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0),
)

# ── Cardinality Protection ───────────────────────────────────────────

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
NUMERIC_ID_PATTERN = re.compile(r"/\d+(?=/|$)")


def normalize_route_template(request: Request) -> str:
    """Extract or construct a bounded route template to prevent cardinality explosion.

    Never uses raw path parameters, UUIDs, or customer-supplied strings.
    """
    # 1. Attempt Starlette router match to get parameterised template
    app = request.app
    if hasattr(app, "routes"):
        for route in app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return getattr(route, "path", request.url.path)

    # 2. Fallback normalization on the raw path
    path = request.url.path
    path = UUID_PATTERN.sub("{id}", path)
    path = NUMERIC_ID_PATTERN.sub("/{id}", path)
    return path or "/"


# ── Middleware ────────────────────────────────────────────────────────


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Starlette middleware to automatically track HTTP request counts and durations."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        # Don't record internal metrics scrape endpoint itself
        if request.url.path == "/metrics":
            res: Response = await call_next(request)
            return res

        method = request.method
        route = normalize_route_template(request)
        service = "shopapi" if route.startswith("/shopapi") else "nexops-api"

        start_time = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            duration = max(time.perf_counter() - start_time, 0.0)
            status_class = f"{status_code // 100}xx"

            HTTP_REQUESTS_TOTAL.labels(
                service=service,
                route=route,
                method=method,
                status_class=status_class,
            ).inc()

            HTTP_REQUEST_DURATION_SECONDS.labels(
                service=service,
                route=route,
                method=method,
            ).observe(duration)


# ── Helper Recording Functions ────────────────────────────────────────


def record_investigation_run(service: str, status: str, duration_seconds: float) -> None:
    """Record an investigation graph run completion."""
    safe_service = service or "unknown"
    safe_status = status or "unknown"
    INVESTIGATION_RUNS_TOTAL.labels(service=safe_service, status=safe_status).inc()
    INVESTIGATION_RUN_DURATION_SECONDS.labels(service=safe_service, status=safe_status).observe(
        max(duration_seconds, 0.0)
    )


def record_evidence_collected(source_type: str, count: int = 1) -> None:
    """Record evidence items collected by branch."""
    safe_type = source_type or "unknown"
    if count > 0:
        EVIDENCE_ITEMS_TOTAL.labels(source_type=safe_type).inc(count)


def record_remediation_action(action_type: str, status: str) -> None:
    """Record sandbox remediation action execution."""
    safe_action = action_type or "unknown"
    safe_status = status or "unknown"
    REMEDIATION_ACTIONS_TOTAL.labels(action_type=safe_action, status=safe_status).inc()


def set_simulator_fault_state(scenario_key: str, active: bool) -> None:
    """Set the active fault gauge for a given simulator scenario."""
    safe_key = scenario_key or "unknown"
    ACTIVE_SIMULATOR_FAULTS.labels(scenario_key=safe_key).set(1.0 if active else 0.0)


def record_llm_invocation(
    provider: str,
    model: str,
    status: str,
    duration_seconds: float,
) -> None:
    """Record LLM call metrics."""
    safe_provider = provider or "fake"
    safe_model = model or "default"
    safe_status = status or "success"
    LLM_REQUESTS_TOTAL.labels(
        provider=safe_provider,
        model=safe_model,
        status=safe_status,
    ).inc()
    LLM_REQUEST_DURATION_SECONDS.labels(
        provider=safe_provider,
        model=safe_model,
    ).observe(max(duration_seconds, 0.0))


def get_metrics_response() -> Response:
    """Format and return the Prometheus exposition response."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

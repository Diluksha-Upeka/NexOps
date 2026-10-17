"""Observability, metrics, tracing, and resilience package (Phase 7).

Provides:
- Prometheus metrics collection and HTTP middleware
- OpenTelemetry distributed tracing and span context management
- Correlation context variables (request_id, trace_id, span_id, run_id)
- Resilience timeouts, transient retries with exponential backoff & jitter, and provider fallback
"""

from __future__ import annotations

from app.observability.context import (
    request_id_var,
    run_id_var,
    set_correlation_context,
    span_id_var,
    trace_id_var,
)
from app.observability.metrics import (
    ACTIVE_SIMULATOR_FAULTS,
    EVIDENCE_ITEMS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    INVESTIGATION_RUN_DURATION_SECONDS,
    INVESTIGATION_RUNS_TOTAL,
    LLM_REQUEST_DURATION_SECONDS,
    LLM_REQUESTS_TOTAL,
    REMEDIATION_ACTIONS_TOTAL,
    PrometheusMetricsMiddleware,
    get_metrics_response,
    normalize_route_template,
    record_evidence_collected,
    record_investigation_run,
    record_llm_invocation,
    record_remediation_action,
    set_simulator_fault_state,
)
from app.observability.resilience import (
    TRANSIENT_EXCEPTIONS,
    ResilientTimeoutError,
    execute_with_provider_fallback,
    retry_transient_async,
    with_timeout,
)
from app.observability.tracing import (
    TracingMiddleware,
    get_current_span_id,
    get_current_trace_id,
    get_tracer,
    init_tracing,
    shutdown_tracing,
    trace_span,
)

__all__ = [
    "ACTIVE_SIMULATOR_FAULTS",
    "EVIDENCE_ITEMS_TOTAL",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "INVESTIGATION_RUNS_TOTAL",
    "INVESTIGATION_RUN_DURATION_SECONDS",
    "LLM_REQUESTS_TOTAL",
    "LLM_REQUEST_DURATION_SECONDS",
    "REMEDIATION_ACTIONS_TOTAL",
    "TRANSIENT_EXCEPTIONS",
    "PrometheusMetricsMiddleware",
    "ResilientTimeoutError",
    "TracingMiddleware",
    "execute_with_provider_fallback",
    "get_current_span_id",
    "get_current_trace_id",
    "get_metrics_response",
    "get_tracer",
    "init_tracing",
    "normalize_route_template",
    "record_evidence_collected",
    "record_investigation_run",
    "record_llm_invocation",
    "record_remediation_action",
    "request_id_var",
    "retry_transient_async",
    "run_id_var",
    "set_correlation_context",
    "set_simulator_fault_state",
    "shutdown_tracing",
    "span_id_var",
    "trace_id_var",
    "trace_span",
    "with_timeout",
]

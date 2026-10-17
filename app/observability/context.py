"""Context variables for request correlation, distributed tracing, and investigation runs.

Provides thread-safe and async-safe context variable storage for:
- request_id: UUID of the current HTTP request
- trace_id: 32-character hex trace ID
- span_id: 16-character hex span ID
- run_id: UUID of the active LangGraph investigation run
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
span_id_var: ContextVar[str | None] = ContextVar("span_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)


def set_correlation_context(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Helper to set active correlation context."""
    if request_id is not None:
        request_id_var.set(request_id)
    if trace_id is not None:
        trace_id_var.set(trace_id)
    if span_id is not None:
        span_id_var.set(span_id)
    if run_id is not None:
        run_id_var.set(run_id)
    return {
        "request_id": request_id_var.get(),
        "trace_id": trace_id_var.get(),
        "span_id": span_id_var.get(),
        "run_id": run_id_var.get(),
    }

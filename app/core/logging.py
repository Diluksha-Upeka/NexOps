"""Structured JSON logging configuration with distributed trace correlation.

Sets up Python's standard logging with JSON-formatted output so that
every log line is machine-parseable and correlated with active HTTP requests,
LangGraph investigation runs, and OpenTelemetry trace spans.
Secrets and large payloads are never passed to log calls.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from app.observability.context import (
    request_id_var,
    run_id_var,
    span_id_var,
    trace_id_var,
)


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line with correlation metadata."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Correlate with active OpenTelemetry span
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.is_valid:
            log_entry["trace_id"] = format(ctx.trace_id, "032x")
            log_entry["span_id"] = format(ctx.span_id, "016x")
        else:
            tid = trace_id_var.get()
            sid = span_id_var.get()
            if tid:
                log_entry["trace_id"] = tid
            if sid:
                log_entry["span_id"] = sid

        # Correlate with active request and investigation run
        req_id = request_id_var.get()
        if req_id:
            log_entry["request_id"] = req_id

        r_id = run_id_var.get()
        if r_id:
            log_entry["run_id"] = r_id

        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Allow extra structured fields via `extra={"structured": {...}}`
        structured: dict[str, Any] | None = getattr(record, "structured", None)
        if structured:
            log_entry["details"] = structured

        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger with JSON output to stderr."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove existing handlers to avoid duplicate output on reload
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

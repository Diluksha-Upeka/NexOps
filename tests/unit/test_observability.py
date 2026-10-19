"""Unit tests for Phase 7 — Observability and Resilience.

Covers:
- Prometheus metrics collection, route template normalization, and /metrics exposition
- Simulator active fault gauge updates
- OpenTelemetry trace spans, context extraction, and response headers
- Structured JSON logging correlation with trace_id, span_id, and request_id
- Resilience timeouts, transient retries with exponential backoff & jitter, and provider fallback
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.logging import JSONFormatter
from app.incidents.evidence_tools import ToolResult, query_logs
from app.main import create_app
from app.observability import (
    ACTIVE_SIMULATOR_FAULTS,
    EVIDENCE_ITEMS_TOTAL,
    INVESTIGATION_RUNS_TOTAL,
    LLM_REQUESTS_TOTAL,
    REMEDIATION_ACTIONS_TOTAL,
    ResilientTimeoutError,
    execute_with_provider_fallback,
    get_current_span_id,
    get_current_trace_id,
    normalize_route_template,
    record_evidence_collected,
    record_investigation_run,
    record_remediation_action,
    retry_transient_async,
    set_correlation_context,
    set_simulator_fault_state,
    trace_span,
    with_timeout,
)
from app.observability.context import (
    span_id_var,
    trace_id_var,
)

# ── Metrics Tests ─────────────────────────────────────────────────────


def test_metrics_endpoint_returns_prometheus_format() -> None:
    """Verify /metrics returns 200 with Prometheus text exposition."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        body = response.text
        assert "nexops_http_requests_total" in body
        assert "nexops_http_request_duration_seconds" in body


def test_route_template_normalization_prevents_cardinality_explosion() -> None:
    """Verify raw UUIDs and numeric IDs are normalized to prevent label explosion."""
    app = FastAPI()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/incidents/550e8400-e29b-41d4-a716-446655440000",
        "app": app,
        "headers": [],
    }
    req = Request(scope)
    normalized = normalize_route_template(req)
    assert "550e8400-e29b-41d4-a716-446655440000" not in normalized
    assert "{id}" in normalized


def test_record_investigation_run_increments_counter() -> None:
    """Verify investigation run counter tracks service and outcome status."""
    service = f"test-svc-{uuid.uuid4().hex[:6]}"
    record_investigation_run(service=service, status="analyzed", duration_seconds=1.2)
    val = INVESTIGATION_RUNS_TOTAL.labels(service=service, status="analyzed")._value.get()
    assert val >= 1.0


def test_record_evidence_collected_metric() -> None:
    """Verify evidence items metric increments by branch type."""
    src = f"test-src-{uuid.uuid4().hex[:4]}"
    record_evidence_collected(source_type=src, count=3)
    val = EVIDENCE_ITEMS_TOTAL.labels(source_type=src)._value.get()
    assert val == 3.0


def test_record_remediation_action_metric() -> None:
    """Verify remediation action metric tracks action type and status."""
    action = f"act-{uuid.uuid4().hex[:4]}"
    record_remediation_action(action_type=action, status="success")
    val = REMEDIATION_ACTIONS_TOTAL.labels(action_type=action, status="success")._value.get()
    assert val >= 1.0


def test_set_simulator_fault_state_gauge() -> None:
    """Verify gauge accurately tracks active vs inactive simulator faults."""
    scenario = f"scenario-{uuid.uuid4().hex[:4]}"
    set_simulator_fault_state(scenario, True)
    assert ACTIVE_SIMULATOR_FAULTS.labels(scenario_key=scenario)._value.get() == 1.0

    set_simulator_fault_state(scenario, False)
    assert ACTIVE_SIMULATOR_FAULTS.labels(scenario_key=scenario)._value.get() == 0.0


# ── Distributed Tracing Tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_span_context_manager() -> None:
    """Verify trace_span creates a span and populates correlation contextvars."""
    token_t = trace_id_var.set(None)
    token_s = span_id_var.set(None)

    async with trace_span("test_operation", attributes={"test.attr": "value"}):
        t_id = get_current_trace_id()
        s_id = get_current_span_id()
        assert t_id is not None
        assert len(t_id) == 32
        assert s_id is not None
        assert len(s_id) == 16

    # Context restored on exit
    trace_id_var.reset(token_t)
    span_id_var.reset(token_s)


def test_tracing_middleware_injects_response_headers() -> None:
    """Verify TracingMiddleware injects x-trace-id and x-request-id into responses."""
    app = create_app()
    with TestClient(app) as client:
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        assert "x-trace-id" in res.headers
        assert "x-request-id" in res.headers
        assert len(res.headers["x-trace-id"]) == 32


# ── Structured Operational Logs Tests ─────────────────────────────────


def test_json_formatter_includes_trace_and_request_correlation() -> None:
    """Verify JSONFormatter extracts trace_id, span_id, and request_id from context."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Operational log message",
        args=(),
        exc_info=None,
    )

    t_id = "0123456789abcdef0123456789abcdef"
    s_id = "abcdef0123456789"
    r_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    set_correlation_context(
        trace_id=t_id,
        span_id=s_id,
        request_id=r_id,
        run_id=run_id,
    )

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["message"] == "Operational log message"
    assert parsed["trace_id"] == t_id
    assert parsed["span_id"] == s_id
    assert parsed["request_id"] == r_id
    assert parsed["run_id"] == run_id

    # Clean up context
    set_correlation_context(trace_id="", span_id="", request_id="", run_id="")


# ── Resilience Tests: Timeouts, Retries, and Fallback ──────────────────


@pytest.mark.asyncio
async def test_with_timeout_success() -> None:
    """Verify with_timeout returns result when operation finishes before deadline."""

    async def fast_op() -> str:
        await asyncio.sleep(0.01)
        return "success"

    res = await with_timeout(fast_op(), timeout_seconds=1.0, operation_name="fast_op")
    assert res == "success"


@pytest.mark.asyncio
async def test_with_timeout_deadline_exceeded() -> None:
    """Verify with_timeout raises ResilientTimeoutError when deadline exceeded."""

    async def slow_op() -> str:
        await asyncio.sleep(0.2)
        return "slow"

    with pytest.raises(ResilientTimeoutError) as exc_info:
        await with_timeout(slow_op(), timeout_seconds=0.05, operation_name="slow_op")

    assert "slow_op" in str(exc_info.value)
    assert exc_info.value.timeout_seconds == 0.05


@pytest.mark.asyncio
async def test_retry_transient_async_recovers_after_transient_failure() -> None:
    """Verify transient connection errors are retried and succeed on subsequent attempt."""
    attempts = 0

    async def flaky_read() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectTimeout("Transient connection drop")
        return "repaired"

    res = await retry_transient_async(
        flaky_read,
        operation_name="flaky_read",
        max_retries=3,
        base_delay=0.01,
        max_delay=0.05,
    )
    assert res == "repaired"
    assert attempts == 3


@pytest.mark.asyncio
async def test_retry_transient_async_exhausts_retries() -> None:
    """Verify retry exhausted re-raises the underlying transient exception."""

    async def always_fails() -> str:
        raise httpx.ConnectError("Service down")

    with pytest.raises(httpx.ConnectError):
        await retry_transient_async(
            always_fails,
            operation_name="always_fails",
            max_retries=2,
            base_delay=0.01,
            max_delay=0.02,
        )


@pytest.mark.asyncio
async def test_retry_transient_async_never_retries_non_transient() -> None:
    """Verify business/validation exceptions (e.g. ValueError) are never retried."""
    attempts = 0

    async def invalid_call() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("Invalid parameters")

    with pytest.raises(ValueError):
        await retry_transient_async(
            invalid_call,
            operation_name="invalid_call",
            max_retries=3,
        )

    # Must fail immediately on first attempt without retry
    assert attempts == 1


@pytest.mark.asyncio
async def test_execute_with_provider_fallback() -> None:
    """Verify primary LLM failure triggers fallback and records fallback metric."""

    async def failing_primary() -> str:
        raise httpx.ReadTimeout("Hosted LLM API timed out")

    async def rule_fallback() -> str:
        return "deterministic_rule_diagnosis"

    provider = f"test-llm-{uuid.uuid4().hex[:4]}"
    result = await execute_with_provider_fallback(
        failing_primary,
        rule_fallback,
        operation_name="root_cause_analysis",
        provider=provider,
        model="gpt-4o",
    )

    assert result == "deterministic_rule_diagnosis"
    val = LLM_REQUESTS_TOTAL.labels(
        provider=provider, model="gpt-4o", status="fallback"
    )._value.get()
    assert val >= 1.0


@pytest.mark.asyncio
async def test_evidence_tool_timeout_reports_structured_error() -> None:
    """Verify tool timeout produces a typed error result rather than crashing."""
    from unittest.mock import MagicMock

    mock_session = AsyncMock()

    async def slow_execute(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(0.5)
        res = MagicMock()
        res.scalars.return_value.all.return_value = []
        return res

    mock_session.execute = slow_execute

    from datetime import timedelta

    mock_settings = MagicMock(tool_timeout_seconds=0.05)

    with patch("app.incidents.evidence_tools.get_settings", return_value=mock_settings):
        result: ToolResult = await query_logs(
            mock_session,
            service="shopapi",
            start=datetime.now(UTC),
            end=datetime.now(UTC) + timedelta(minutes=10),
            limit=10,
        )

        assert result.ok is False
        assert result.error_code == "tool_timeout"
        assert "timed out" in (result.error_message or "")

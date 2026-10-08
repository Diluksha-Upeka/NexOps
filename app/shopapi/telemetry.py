"""Telemetry recording service.

Records structured logs, metric samples, and trace-like spans into the
``telemetry_events`` table.  Each event is tagged with the active scenario
(if any) so evaluation fixtures can link observations to their source
without leaking scenario labels into evidence shown to the graph.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.shopapi.telemetry_models import TelemetryEvent

logger = logging.getLogger(__name__)


class TelemetryRecorder:
    """Records telemetry events to the database."""

    def __init__(self, session: AsyncSession, scenario_id: str | None = None) -> None:
        self._session = session
        self._scenario_id = scenario_id

    async def record_request(
        self,
        *,
        route: str,
        method: str,
        status_code: int,
        duration_ms: float,
        trace_id: str | None = None,
        span_id: str | None = None,
        extra_attributes: dict[str, Any] | None = None,
    ) -> None:
        """Record a metric event for a completed HTTP request."""
        attrs = {
            "route_template": route,
            "method": method,
            "status_class": f"{status_code // 100}xx",
            **(extra_attributes or {}),
        }
        event = TelemetryEvent(
            id=uuid.uuid4(),
            scenario_id=self._scenario_id,
            kind="metric",
            timestamp=datetime.now(UTC),
            service="shopapi",
            route=route,
            method=method,
            status_code=status_code,
            duration_ms=duration_ms,
            trace_id=trace_id,
            span_id=span_id,
            attributes=attrs,
        )
        self._session.add(event)

    async def record_log(
        self,
        *,
        level: str,
        message: str,
        route: str | None = None,
        method: str | None = None,
        status_code: int | None = None,
        trace_id: str | None = None,
        extra_attributes: dict[str, Any] | None = None,
    ) -> None:
        """Record a structured log event."""
        event = TelemetryEvent(
            id=uuid.uuid4(),
            scenario_id=self._scenario_id,
            kind="log",
            timestamp=datetime.now(UTC),
            service="shopapi",
            route=route,
            method=method,
            status_code=status_code,
            level=level,
            message=message,
            trace_id=trace_id,
            attributes=extra_attributes,
        )
        self._session.add(event)

    async def record_span(
        self,
        *,
        name: str,
        duration_ms: float,
        trace_id: str,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        status_code: int | None = None,
        error: bool = False,
        extra_attributes: dict[str, Any] | None = None,
    ) -> None:
        """Record a trace span event."""
        attrs = {
            "span_name": name,
            "error": error,
            **(extra_attributes or {}),
        }
        event = TelemetryEvent(
            id=uuid.uuid4(),
            scenario_id=self._scenario_id,
            kind="span",
            timestamp=datetime.now(UTC),
            service="shopapi",
            duration_ms=duration_ms,
            status_code=status_code,
            trace_id=trace_id,
            span_id=span_id or uuid.uuid4().hex[:16],
            parent_span_id=parent_span_id,
            attributes=attrs,
        )
        self._session.add(event)


def generate_trace_id() -> str:
    """Generate a 32-char hex trace ID."""
    return uuid.uuid4().hex


def generate_span_id() -> str:
    """Generate a 16-char hex span ID."""
    return uuid.uuid4().hex[:16]

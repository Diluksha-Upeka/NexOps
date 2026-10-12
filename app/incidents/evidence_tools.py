"""Read-only evidence tools — bounded queries over simulated telemetry.

These tools are designed to be called by the LangGraph investigation
workflow (Phase 3+), but are independently testable and usable from the
API.  Each tool enforces:
  - Allowed service names
  - Time-window limits (max 24 hours)
  - Result-count limits (max 500 rows)
  - Typed, cited return values

The model never supplies SQL.  Tools query through SQLAlchemy with
parameterised filters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shopapi.simulator import get_simulator
from app.shopapi.telemetry_models import TelemetryEvent

logger = logging.getLogger(__name__)

# ── Configuration / guards ────────────────────────────────────────────

ALLOWED_SERVICES = {"shopapi"}
MAX_WINDOW_HOURS = 24
MAX_RESULTS = 500
DEFAULT_LIMIT = 100


@dataclass
class ToolResult:
    """Typed return value from an evidence tool.

    Every tool returns this structure so the graph can handle
    successes and failures uniformly.
    """

    ok: bool
    data: list[dict[str, Any]] = field(default_factory=list)
    count: int = 0
    error_code: str | None = None
    error_message: str | None = None
    source_ref: str | None = None


def _validate_window(
    service: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> ToolResult | None:
    """Return a ToolResult with an error if any guard fails, else None."""
    if service not in ALLOWED_SERVICES:
        return ToolResult(
            ok=False,
            error_code="invalid_service",
            error_message=(
                f"Service '{service}' not recognised. Allowed: {sorted(ALLOWED_SERVICES)}"
            ),
        )
    if end <= start:
        return ToolResult(
            ok=False,
            error_code="invalid_window",
            error_message="'end' must be after 'start'.",
        )
    window = end - start
    if window > timedelta(hours=MAX_WINDOW_HOURS):
        return ToolResult(
            ok=False,
            error_code="window_too_large",
            error_message=f"Time window exceeds maximum of {MAX_WINDOW_HOURS} hours.",
        )
    if limit < 1 or limit > MAX_RESULTS:
        return ToolResult(
            ok=False,
            error_code="invalid_limit",
            error_message=f"Limit must be between 1 and {MAX_RESULTS}.",
        )
    return None


# ── query_logs ────────────────────────────────────────────────────────


async def query_logs(
    session: AsyncSession,
    *,
    service: str,
    start: datetime,
    end: datetime,
    route: str | None = None,
    severity: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> ToolResult:
    """Query structured log events within a bounded time window.

    Returns log entries with their timestamps, levels, messages,
    and trace IDs for citation.
    """
    err = _validate_window(service, start, end, limit)
    if err:
        return err

    query = (
        select(TelemetryEvent)
        .where(
            TelemetryEvent.kind == "log",
            TelemetryEvent.service == service,
            TelemetryEvent.timestamp >= start,
            TelemetryEvent.timestamp <= end,
        )
        .order_by(TelemetryEvent.timestamp.desc())
        .limit(limit)
    )
    if route:
        query = query.where(TelemetryEvent.route == route)
    if severity:
        query = query.where(TelemetryEvent.level == severity.upper())

    result = await session.execute(query)
    rows = result.scalars().all()

    data = [
        {
            "id": str(r.id),
            "timestamp": r.timestamp.isoformat(),
            "level": r.level,
            "message": r.message,
            "route": r.route,
            "method": r.method,
            "status_code": r.status_code,
            "trace_id": r.trace_id,
        }
        for r in rows
    ]
    return ToolResult(
        ok=True,
        data=data,
        count=len(data),
        source_ref=f"logs:{service}:{start.isoformat()}/{end.isoformat()}",
    )


# ── query_metrics ─────────────────────────────────────────────────────


async def query_metrics(
    session: AsyncSession,
    *,
    service: str,
    start: datetime,
    end: datetime,
    metric: str = "request_duration",
    group_by: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> ToolResult:
    """Query metric events and compute aggregates.

    Supported metrics: request_duration, error_rate, request_count.
    Optional group_by: route, status_code, method.
    """
    err = _validate_window(service, start, end, limit)
    if err:
        return err

    valid_metrics = {"request_duration", "error_rate", "request_count"}
    if metric not in valid_metrics:
        return ToolResult(
            ok=False,
            error_code="invalid_metric",
            error_message=f"Metric '{metric}' not supported. Available: {sorted(valid_metrics)}",
        )

    query = (
        select(TelemetryEvent)
        .where(
            TelemetryEvent.kind == "metric",
            TelemetryEvent.service == service,
            TelemetryEvent.timestamp >= start,
            TelemetryEvent.timestamp <= end,
        )
        .order_by(TelemetryEvent.timestamp.desc())
        .limit(limit)
    )
    result = await session.execute(query)
    rows = list(result.scalars().all())

    if not rows:
        return ToolResult(
            ok=True,
            data=[],
            count=0,
            source_ref=f"metrics:{service}:{start.isoformat()}/{end.isoformat()}",
        )

    # Compute aggregates based on the metric type
    aggregates: dict[str, Any] = {"sample_count": len(rows)}

    if metric == "request_duration":
        durations = [r.duration_ms for r in rows if r.duration_ms is not None]
        if durations:
            durations_sorted = sorted(durations)
            aggregates.update(
                {
                    "min_ms": round(min(durations), 1),
                    "max_ms": round(max(durations), 1),
                    "avg_ms": round(sum(durations) / len(durations), 1),
                    "p50_ms": round(durations_sorted[len(durations_sorted) // 2], 1),
                    "p95_ms": round(durations_sorted[int(len(durations_sorted) * 0.95)], 1),
                }
            )

    elif metric == "error_rate":
        total = len(rows)
        errors = sum(1 for r in rows if r.status_code is not None and r.status_code >= 500)
        aggregates.update(
            {
                "total_requests": total,
                "error_count": errors,
                "error_rate": round(errors / total, 4) if total > 0 else 0,
            }
        )

    elif metric == "request_count":
        aggregates["total_requests"] = len(rows)

    # Group by if requested
    grouped: dict[str, int] = {}
    valid_groups = {"route", "status_code", "method"}
    if group_by and group_by in valid_groups:
        for r in rows:
            key = str(getattr(r, group_by, "unknown"))
            grouped[key] = grouped.get(key, 0) + 1
        aggregates["grouped_by"] = group_by
        aggregates["groups"] = grouped

    return ToolResult(
        ok=True,
        data=[aggregates],
        count=len(rows),
        source_ref=f"metrics:{service}:{metric}:{start.isoformat()}/{end.isoformat()}",
    )


# ── query_traces ──────────────────────────────────────────────────────


async def query_traces(
    session: AsyncSession,
    *,
    service: str,
    start: datetime,
    end: datetime,
    trace_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> ToolResult:
    """Query trace span events within a bounded time window.

    Can filter by a specific trace_id to reconstruct a distributed trace.
    """
    err = _validate_window(service, start, end, limit)
    if err:
        return err

    query = (
        select(TelemetryEvent)
        .where(
            TelemetryEvent.kind == "span",
            TelemetryEvent.service == service,
            TelemetryEvent.timestamp >= start,
            TelemetryEvent.timestamp <= end,
        )
        .order_by(TelemetryEvent.timestamp.desc())
        .limit(limit)
    )
    if trace_id:
        query = query.where(TelemetryEvent.trace_id == trace_id)

    result = await session.execute(query)
    rows = result.scalars().all()

    data = [
        {
            "id": str(r.id),
            "timestamp": r.timestamp.isoformat(),
            "trace_id": r.trace_id,
            "span_id": r.span_id,
            "parent_span_id": r.parent_span_id,
            "duration_ms": r.duration_ms,
            "status_code": r.status_code,
            "attributes": r.attributes,
        }
        for r in rows
    ]
    return ToolResult(
        ok=True,
        data=data,
        count=len(data),
        source_ref=f"traces:{service}:{start.isoformat()}/{end.isoformat()}",
    )


# ── query_changes ─────────────────────────────────────────────────────


async def query_changes(
    service: str,
    start: datetime,
    end: datetime,
    limit: int = DEFAULT_LIMIT,
) -> ToolResult:
    """Query simulated deployment/config change history.

    Change history is kept in-memory by the simulator (Phase 1).
    This does not hit the database — it reads from simulator state.
    """
    err = _validate_window(service, start, end, limit)
    if err:
        return err

    simulator = get_simulator()
    all_changes = simulator.change_history

    # Filter changes within the time window
    filtered = []
    for change in all_changes:
        ts_str = change.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            continue
        if start <= ts <= end and change.get("service", "") == service:
            filtered.append(change)

    filtered = filtered[:limit]

    return ToolResult(
        ok=True,
        data=filtered,
        count=len(filtered),
        source_ref=f"changes:{service}:{start.isoformat()}/{end.isoformat()}",
    )


# ── get_simulator_status ──────────────────────────────────────────────


async def get_simulator_status(service: str) -> ToolResult:
    """Get the current simulator status for a service."""
    if service not in ALLOWED_SERVICES:
        return ToolResult(
            ok=False,
            error_code="invalid_service",
            error_message=f"Service '{service}' not recognised.",
        )

    simulator = get_simulator()
    active = simulator.active_faults

    data = [
        {
            "scenario": k.value,
            "started_at": f.started_at_utc,
            "remaining_seconds": round(f.remaining_seconds, 1),
            "parameters": f.parameters,
        }
        for k, f in active.items()
    ]
    return ToolResult(
        ok=True,
        data=data,
        count=len(data),
        source_ref=f"simulator_status:{service}",
    )

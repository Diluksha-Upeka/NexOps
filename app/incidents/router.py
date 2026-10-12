"""Incident HTTP routers.

Exposes CRUD for incidents, investigation runs, evidence queries,
and audit trail.  Route handlers are thin — they delegate to the
IncidentService and evidence tools.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.incidents.evidence_tools import (
    query_changes,
    query_logs,
    query_metrics,
    query_traces,
)
from app.incidents.schemas import (
    AuditEventResponse,
    CreateIncidentRequest,
    EvidenceItemResponse,
    IncidentListResponse,
    IncidentResponse,
    InvestigationRunResponse,
    ResolveIncidentRequest,
)
from app.incidents.service import (
    IncidentNotFoundError,
    IncidentService,
    InvalidTransitionError,
)

router = APIRouter(prefix="/api/v1", tags=["incidents"])


# ── Incidents ─────────────────────────────────────────────────────────


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    status: str | None = Query(None),
    service: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> IncidentListResponse:
    """List incidents with optional filters."""
    svc = IncidentService(session)
    incidents, total = await svc.list_incidents(
        status=status,
        service=service,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return IncidentListResponse(
        items=[IncidentResponse.model_validate(i) for i in incidents],
        total=total,
    )


@router.post("/incidents", response_model=IncidentResponse, status_code=201)
async def create_incident(
    body: CreateIncidentRequest,
    session: AsyncSession = Depends(get_session),
) -> IncidentResponse:
    """Create a new incident (manual or simulator-triggered)."""
    svc = IncidentService(session)
    incident = await svc.create_incident(
        title=body.title,
        description=body.description,
        service=body.service,
        severity=body.severity,
        source=body.source,
        scenario_key=body.scenario_key,
    )
    return IncidentResponse.model_validate(incident)


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> IncidentResponse:
    """Get a single incident by ID."""
    svc = IncidentService(session)
    incident = await svc.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentResponse.model_validate(incident)


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentResponse)
async def resolve_incident(
    incident_id: uuid.UUID,
    body: ResolveIncidentRequest,
    session: AsyncSession = Depends(get_session),
) -> IncidentResponse:
    """Manually resolve an incident with an audited reason."""
    svc = IncidentService(session)
    try:
        incident = await svc.resolve_incident(incident_id, reason=body.reason, actor=body.actor)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IncidentResponse.model_validate(incident)


# ── Investigation Runs ────────────────────────────────────────────────


@router.post(
    "/incidents/{incident_id}/investigations",
    response_model=InvestigationRunResponse,
    status_code=202,
)
async def start_investigation(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> InvestigationRunResponse:
    """Start a new investigation run for an incident (returns 202)."""
    svc = IncidentService(session)
    try:
        run = await svc.create_run(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return InvestigationRunResponse.model_validate(run)


@router.get("/runs/{run_id}", response_model=InvestigationRunResponse)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> InvestigationRunResponse:
    """Get a single investigation run by ID."""
    svc = IncidentService(session)
    run = await svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    return InvestigationRunResponse.model_validate(run)


@router.get(
    "/incidents/{incident_id}/runs",
    response_model=list[InvestigationRunResponse],
)
async def list_runs(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[InvestigationRunResponse]:
    """List all investigation runs for an incident."""
    svc = IncidentService(session)
    runs = await svc.list_runs_for_incident(incident_id)
    return [InvestigationRunResponse.model_validate(r) for r in runs]


# ── Evidence ──────────────────────────────────────────────────────────


@router.get(
    "/runs/{run_id}/evidence",
    response_model=list[EvidenceItemResponse],
)
async def get_evidence(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[EvidenceItemResponse]:
    """Get all evidence items for an investigation run."""
    svc = IncidentService(session)
    run = await svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    evidence = await svc.get_evidence_for_run(run_id)
    return [EvidenceItemResponse.model_validate(e) for e in evidence]


# ── Evidence Tools (bounded telemetry queries) ────────────────────────


@router.get("/tools/logs")
async def tool_query_logs(
    service: str = Query("shopapi"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    route: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Query structured log events (bounded read-only tool)."""
    now = datetime.now(UTC)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    result = await query_logs(
        session,
        service=service,
        start=start,
        end=end,
        route=route,
        severity=severity,
        limit=limit,
    )
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.error_message)
    return {"ok": True, "data": result.data, "count": result.count, "source_ref": result.source_ref}


@router.get("/tools/metrics")
async def tool_query_metrics(
    service: str = Query("shopapi"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    metric: str = Query("request_duration"),
    group_by: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Query metric events and compute aggregates (bounded read-only tool)."""
    now = datetime.now(UTC)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    result = await query_metrics(
        session,
        service=service,
        start=start,
        end=end,
        metric=metric,
        group_by=group_by,
        limit=limit,
    )
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.error_message)
    return {"ok": True, "data": result.data, "count": result.count, "source_ref": result.source_ref}


@router.get("/tools/traces")
async def tool_query_traces(
    service: str = Query("shopapi"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    trace_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Query trace spans (bounded read-only tool)."""
    now = datetime.now(UTC)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    result = await query_traces(
        session,
        service=service,
        start=start,
        end=end,
        trace_id=trace_id,
        limit=limit,
    )
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.error_message)
    return {"ok": True, "data": result.data, "count": result.count, "source_ref": result.source_ref}


@router.get("/tools/changes")
async def tool_query_changes(
    service: str = Query("shopapi"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Query deployment/config change history (bounded read-only tool)."""
    now = datetime.now(UTC)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    result = await query_changes(
        service=service,
        start=start,
        end=end,
        limit=limit,
    )
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.error_message)
    return {"ok": True, "data": result.data, "count": result.count, "source_ref": result.source_ref}


# ── Audit Trail ───────────────────────────────────────────────────────


@router.get(
    "/incidents/{incident_id}/audit",
    response_model=list[AuditEventResponse],
)
async def get_incident_audit(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[AuditEventResponse]:
    """Get the audit trail for an incident."""
    svc = IncidentService(session)
    incident = await svc.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    events = await svc.get_audit_trail("incident", str(incident_id))
    return [AuditEventResponse.model_validate(e) for e in events]

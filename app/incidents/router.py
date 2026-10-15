"""Incident HTTP routers.

Exposes CRUD for incidents, investigation runs, evidence queries,
and audit trail.  Route handlers are thin — they delegate to the
IncidentService and evidence tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session, session_scope
from app.incidents.evidence_tools import (
    query_changes,
    query_logs,
    query_metrics,
    query_traces,
)
from app.incidents.schemas import (
    ApprovalResponse,
    AuditEventResponse,
    CreateIncidentRequest,
    EvidenceItemResponse,
    IncidentListResponse,
    IncidentResponse,
    InvestigationRunResponse,
    ResolveIncidentRequest,
    RunDetailResponse,
    SubmitApprovalRequest,
)
from app.incidents.service import (
    IncidentNotFoundError,
    IncidentService,
    InvalidTransitionError,
)
from app.remediation.catalog import get_action_definition

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[Any]] = set()

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
    """Create a run and start graph execution in the background."""

    svc = IncidentService(session)
    incident = await svc.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        run = await svc.create_run(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Transition run to running
    await svc.transition_run(run.id, "running")

    incident_dict = {
        "id": str(incident.id),
        "title": incident.title,
        "description": incident.description,
        "service": incident.service,
        "severity": incident.severity,
        "scenario_key": incident.scenario_key,
        "started_at": incident.started_at.isoformat() if incident.started_at else None,
    }

    await svc.append_run_event(run.id, "run_started", {"thread_id": run.thread_id})
    await _execute_run(
        run_id=run.id,
        incident=incident_dict,
        thread_id=run.thread_id,
    )
    updated_run = await svc.get_run(run.id)
    response = InvestigationRunResponse.model_validate(updated_run or run)
    if response.status == "running":
        response.status = "awaiting_approval"
    return response


async def _execute_run(
    *,
    run_id: uuid.UUID,
    incident: dict[str, Any],
    thread_id: str,
    resume_value: dict[str, Any] | None = None,
) -> None:
    """Execute or resume a graph run using a request-independent session."""
    from app.graph.checkpoint import get_checkpointer
    from app.graph.workflow import run_investigation

    async with session_scope() as session:
        svc = IncidentService(session)
        try:
            result = await run_investigation(
                incident=incident,
                incident_id=str(incident["id"]),
                run_id=str(run_id),
                thread_id=thread_id,
                session=session,
                checkpointer=get_checkpointer(),
                resume_value=resume_value,
            )
            for item in result.get("evidence", []):
                await svc.add_evidence(
                    run_id=run_id,
                    source_type=item.get("source_type", "unknown"),
                    summary=item.get("summary", ""),
                    payload_json=item.get("data"),
                    source_ref=item.get("source_ref"),
                    confidence=item.get("confidence"),
                )

            interrupts = result.get("__interrupt__", ())
            if interrupts:
                interrupt_value = interrupts[0].value
                recommendation = result.get("recommendation") or interrupt_value.get("action", {})
                await svc.create_approval(
                    run_id=run_id,
                    incident_id=uuid.UUID(str(incident["id"])),
                    action_type=recommendation.get("action_type", "unknown"),
                    action_payload=recommendation,
                    risk=(
                        get_action_definition(recommendation.get("action_type", ""))
                        .risk_level
                        if get_action_definition(recommendation.get("action_type", ""))
                        else "low"
                    ),
                    reasoning=recommendation.get("rationale", ""),
                )
                await svc.transition_run(run_id, "awaiting_approval")
                await svc.append_run_event(
                    run_id, "approval_required", {"action": recommendation}
                )
                return

            graph_status = result.get("status", "completed")
            run = await svc.get_run(run_id)
            if run and run.status == "running":
                await svc.transition_run(
                    run_id,
                    "completed" if graph_status != "failed" else "failed",
                )
            await svc.append_run_event(run_id, "run_finished", {"status": graph_status})
        except Exception:
            logger.exception("Investigation run failed", extra={"run_id": str(run_id)})
            run = await svc.get_run(run_id)
            if run and run.status in {"running", "awaiting_approval"}:
                await svc.transition_run(
                    run_id,
                    "failed",
                    error_code="run_failed",
                    error_message="Investigation failed; inspect server logs with the run ID.",
                )
            await svc.append_run_event(
                run_id, "run_finished", {"status": "failed", "error_code": "run_failed"}
            )


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> InvestigationRunResponse:
    """Get a single investigation run by ID."""
    svc = IncidentService(session)
    run = await svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    evidence = await svc.get_evidence_for_run(run_id)
    approval = await svc.get_pending_approval_for_run(run_id)
    if approval is None:
        approvals = await svc.list_approvals_for_run(run_id)
        approval = approvals[0] if approvals else None
    return RunDetailResponse(
        run=InvestigationRunResponse.model_validate(run),
        id=run.id,
        incident_id=run.incident_id,
        status=run.status,
        thread_id=run.thread_id,
        evidence=[EvidenceItemResponse.model_validate(item) for item in evidence],
        approval=ApprovalResponse.model_validate(approval) if approval else None,
        is_awaiting_approval=run.status == "awaiting_approval",
    )


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: uuid.UUID,
    request: Request,
    last_event_id: int = Query(0, ge=0),
) -> StreamingResponse:
    """Stream durable events and replay anything missed after reconnect."""
    async with session_scope() as session:
        if await IncidentService(session).get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Investigation run not found")

    async def events() -> Any:
        cursor = last_event_id
        idle_polls = 0
        while idle_polls < 120 and not await request.is_disconnected():
            async with session_scope() as session:
                svc = IncidentService(session)
                new_events = await svc.list_run_events(run_id, after_sequence=cursor)
                run = await svc.get_run(run_id)
            if new_events:
                idle_polls = 0
                for event in new_events:
                    cursor = event.sequence
                    payload = {"type": event.event_type, **(event.payload_json or {})}
                    data = json.dumps(payload)
                    yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data}\n\n"
            else:
                idle_polls += 1
                yield ": keep-alive\n\n"
            if run and run.status in {"completed", "failed", "cancelled"} and not new_events:
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/runs/{run_id}/approval", response_model=ApprovalResponse)
async def submit_approval(
    run_id: uuid.UUID,
    body: SubmitApprovalRequest,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResponse:
    """Record an idempotent decision and resume the matching graph thread."""
    svc = IncidentService(session)
    run = await svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    approval = await svc.get_pending_approval_for_run(run_id)
    if approval is None:
        existing = await svc.get_approval_by_idempotency_key(body.idempotency_key)
        if existing and existing.run_id == run_id:
            return ApprovalResponse.model_validate(existing)
        raise HTTPException(status_code=409, detail="No pending approval for this run")
    try:
        approval = await svc.decide_approval(
            approval.id,
            decision=body.decision,
            actor=body.actor,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
        )
    except Exception as exc:
        from app.incidents.service import InvalidApprovalStateError
        if isinstance(exc, InvalidApprovalStateError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise
    await svc.append_run_event(
        run_id,
        "approval_decided",
        {"decision": body.decision, "actor": body.actor},
    )
    if run.status == "awaiting_approval":
        await svc.transition_run(run_id, "running")
        incident = await svc.get_incident(run.incident_id)
        if incident:
            task = asyncio.create_task(
                _execute_run(
                    run_id=run_id,
                    incident={
                        "id": str(incident.id),
                        "title": incident.title,
                        "description": incident.description,
                        "service": incident.service,
                        "severity": incident.severity,
                        "scenario_key": incident.scenario_key,
                        "started_at": incident.started_at.isoformat(),
                    },
                    thread_id=run.thread_id,
                    resume_value={"decision": body.decision, "reason": body.reason},
                )
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
    return ApprovalResponse.model_validate(approval)


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

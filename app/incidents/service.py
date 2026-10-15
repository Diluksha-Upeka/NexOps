"""Incident lifecycle service — state machine, audit, and domain logic.

All status transitions are validated against an explicit allowed-transition
map.  Every transition records an audit event.  Investigation-run status
is kept distinct from incident status.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.models import (
    Approval,
    AuditEvent,
    EvidenceItem,
    Incident,
    InvestigationRun,
    RunEvent,
)

logger = logging.getLogger(__name__)

# ── Incident status transitions ──────────────────────────────────────

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"investigating", "resolved"},
    "investigating": {"awaiting_approval", "open", "resolved"},
    "awaiting_approval": {"remediating", "investigating", "open", "resolved"},
    "remediating": {"verifying", "open", "resolved"},
    "verifying": {"resolved", "mitigated", "open"},
    "mitigated": {"open", "resolved"},
    "resolved": {"open"},  # reopen
}

# ── Run status transitions ───────────────────────────────────────────

RUN_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "cancelled"},
    "running": {"awaiting_approval", "completed", "failed", "cancelled"},
    "awaiting_approval": {"running", "completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


class IncidentService:
    """Domain service for incident lifecycle operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Incident CRUD ─────────────────────────────────────────────────

    async def create_incident(
        self,
        *,
        title: str,
        description: str = "",
        service: str = "shopapi",
        severity: str = "medium",
        source: str = "manual",
        scenario_key: str | None = None,
        actor: str = "system",
    ) -> Incident:
        """Create a new incident and record an audit event."""
        incident = Incident(
            title=title,
            description=description,
            service=service,
            severity=severity,
            status="open",
            source=source,
            scenario_key=scenario_key,
        )
        self._session.add(incident)
        await self._session.flush()

        await self._audit(
            actor=actor,
            event_type="incident_created",
            resource_type="incident",
            resource_id=str(incident.id),
            details={
                "title": title,
                "service": service,
                "severity": severity,
                "source": source,
                "scenario_key": scenario_key,
            },
        )
        await self._session.commit()
        return incident

    async def get_incident(self, incident_id: uuid.UUID) -> Incident | None:
        """Fetch a single incident by ID."""
        result = await self._session.execute(select(Incident).where(Incident.id == incident_id))
        return result.scalar_one_or_none()

    async def list_incidents(
        self,
        *,
        status: str | None = None,
        service: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        """List incidents with optional filters, ordered by creation time."""
        query = select(Incident)
        count_query = select(func.count(Incident.id))

        if status:
            query = query.where(Incident.status == status)
            count_query = count_query.where(Incident.status == status)
        if service:
            query = query.where(Incident.service == service)
            count_query = count_query.where(Incident.service == service)
        if severity:
            query = query.where(Incident.severity == severity)
            count_query = count_query.where(Incident.severity == severity)

        total = (await self._session.execute(count_query)).scalar_one()
        result = await self._session.execute(
            query.order_by(Incident.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def transition_incident(
        self,
        incident_id: uuid.UUID,
        new_status: str,
        *,
        actor: str = "system",
        reason: str | None = None,
    ) -> Incident:
        """Transition an incident to a new status with validation and audit."""
        incident = await self.get_incident(incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"Incident {incident_id} not found")

        old_status = incident.status
        allowed = ALLOWED_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition incident from '{old_status}' to '{new_status}'. "
                f"Allowed: {sorted(allowed)}"
            )

        incident.status = new_status
        incident.version += 1

        if new_status == "resolved":
            incident.resolved_at = datetime.now(UTC)

        await self._audit(
            actor=actor,
            event_type="status_changed",
            resource_type="incident",
            resource_id=str(incident_id),
            details={
                "from": old_status,
                "to": new_status,
                "reason": reason,
            },
        )
        await self._session.commit()
        return incident

    async def resolve_incident(
        self,
        incident_id: uuid.UUID,
        *,
        reason: str,
        actor: str = "dev-user",
    ) -> Incident:
        """Resolve an incident with an audited reason."""
        return await self.transition_incident(incident_id, "resolved", actor=actor, reason=reason)

    # ── Investigation Run operations ──────────────────────────────────

    async def create_run(
        self,
        incident_id: uuid.UUID,
        *,
        actor: str = "system",
    ) -> InvestigationRun:
        """Create a new investigation run for an incident."""
        incident = await self.get_incident(incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"Incident {incident_id} not found")

        run = InvestigationRun(
            incident_id=incident_id,
            thread_id=f"thread-{uuid.uuid4().hex[:12]}",
            status="pending",
        )
        self._session.add(run)
        await self._session.flush()

        # Transition incident to investigating (if not already)
        if incident.status == "open":
            await self.transition_incident(incident_id, "investigating", actor=actor)

        await self._audit(
            actor=actor,
            event_type="investigation_started",
            resource_type="investigation_run",
            resource_id=str(run.id),
            details={"incident_id": str(incident_id), "thread_id": run.thread_id},
        )
        await self._session.commit()
        return run

    async def get_run(self, run_id: uuid.UUID) -> InvestigationRun | None:
        """Fetch a single investigation run by ID."""
        result = await self._session.execute(
            select(InvestigationRun).where(InvestigationRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_runs_for_incident(self, incident_id: uuid.UUID) -> list[InvestigationRun]:
        """List all runs for an incident, newest first."""
        result = await self._session.execute(
            select(InvestigationRun)
            .where(InvestigationRun.incident_id == incident_id)
            .order_by(InvestigationRun.started_at.desc())
        )
        return list(result.scalars().all())

    async def transition_run(
        self,
        run_id: uuid.UUID,
        new_status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> InvestigationRun:
        """Transition a run to a new status with validation."""
        run = await self.get_run(run_id)
        if run is None:
            raise RunNotFoundError(f"Run {run_id} not found")

        old_status = run.status
        allowed = RUN_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition run from '{old_status}' to '{new_status}'. "
                f"Allowed: {sorted(allowed)}"
            )

        run.status = new_status
        if new_status in ("completed", "failed", "cancelled"):
            run.finished_at = datetime.now(UTC)
        if error_code:
            run.error_code = error_code
        if error_message:
            run.error_message = error_message

        await self._session.commit()
        return run

    # ── Evidence operations ───────────────────────────────────────────

    async def add_evidence(
        self,
        run_id: uuid.UUID,
        *,
        source_type: str,
        summary: str,
        payload_json: dict[str, Any] | None = None,
        source_ref: str | None = None,
        confidence: float | None = None,
    ) -> EvidenceItem:
        """Add an immutable evidence item to a run."""
        evidence = EvidenceItem(
            run_id=run_id,
            source_type=source_type,
            summary=summary,
            payload_json=payload_json,
            source_ref=source_ref,
            confidence=confidence,
            simulated=True,
        )
        self._session.add(evidence)
        await self._session.commit()
        return evidence

    async def get_evidence_for_run(self, run_id: uuid.UUID) -> list[EvidenceItem]:
        """Fetch all evidence items for a run."""
        result = await self._session.execute(
            select(EvidenceItem)
            .where(EvidenceItem.run_id == run_id)
            .order_by(EvidenceItem.observed_at)
        )
        return list(result.scalars().all())

    # ── Approval operations ───────────────────────────────────────────

    async def create_approval(
        self,
        *,
        run_id: uuid.UUID,
        incident_id: uuid.UUID,
        action_type: str,
        action_payload: dict[str, Any] | None = None,
        risk: str = "low",
        reasoning: str = "",
        actor: str = "system",
    ) -> Approval:
        """Create a pending approval request for a proposed remediation action."""
        approval = Approval(
            run_id=run_id,
            incident_id=incident_id,
            action_type=action_type,
            action_payload=action_payload,
            status="pending",
            risk=risk,
            reasoning=reasoning,
        )
        self._session.add(approval)
        await self._audit(
            actor=actor,
            event_type="approval_requested",
            resource_type="approval",
            resource_id=str(approval.id),
            details={
                "run_id": str(run_id),
                "incident_id": str(incident_id),
                "action_type": action_type,
                "risk": risk,
            },
        )
        await self._session.commit()
        return approval

    async def get_approval(self, approval_id: uuid.UUID) -> Approval | None:
        """Fetch an approval by ID."""
        result = await self._session.execute(select(Approval).where(Approval.id == approval_id))
        return result.scalar_one_or_none()

    async def get_pending_approval_for_run(self, run_id: uuid.UUID) -> Approval | None:
        """Fetch the current pending approval request for a run."""
        result = await self._session.execute(
            select(Approval)
            .where(Approval.run_id == run_id, Approval.status == "pending")
            .order_by(Approval.created_at.desc())
        )
        return result.scalars().first()

    async def get_approval_by_idempotency_key(self, key: str) -> Approval | None:
        """Fetch an approval by idempotency key to prevent duplicate submissions."""
        result = await self._session.execute(
            select(Approval).where(Approval.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def list_approvals_for_run(self, run_id: uuid.UUID) -> list[Approval]:
        """List all approvals for a run."""
        result = await self._session.execute(
            select(Approval).where(Approval.run_id == run_id).order_by(Approval.created_at.desc())
        )
        return list(result.scalars().all())

    async def append_run_event(
        self,
        run_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        """Append a monotonically sequenced event for SSE replay."""
        latest = await self._session.execute(
            select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)
        )
        sequence = (latest.scalar_one() or 0) + 1
        event = RunEvent(
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
            payload_json=payload,
        )
        self._session.add(event)
        await self._session.commit()
        return event

    async def list_run_events(
        self, run_id: uuid.UUID, *, after_sequence: int = 0
    ) -> list[RunEvent]:
        """Return events after a client-provided replay cursor."""
        result = await self._session.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.sequence > after_sequence)
            .order_by(RunEvent.sequence)
        )
        return list(result.scalars().all())

    async def decide_approval(
        self,
        approval_id: uuid.UUID,
        *,
        decision: str,
        actor: str,
        reason: str = "",
        idempotency_key: str | None = None,
    ) -> Approval:
        """Record an operator's decision on a pending approval.

        Valid decisions: 'approved', 'rejected', 'request_more_evidence'.
        """
        approval = await self.get_approval(approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} not found")

        # Idempotency check: if already decided with same key and decision, return as-is
        if idempotency_key and approval.idempotency_key == idempotency_key:
            return approval

        if approval.status != "pending":
            raise InvalidApprovalStateError(f"Cannot decide approval in '{approval.status}' state.")

        status_map = {
            "approved": "approved",
            "rejected": "rejected",
            "request_more_evidence": "requested_more_evidence",
        }
        new_status = status_map.get(decision)
        if not new_status:
            raise ValueError(f"Unknown decision: {decision}")

        approval.status = new_status
        approval.actor = actor
        approval.decision_reason = reason
        approval.decided_at = datetime.now(UTC)
        if idempotency_key:
            approval.idempotency_key = idempotency_key

        await self._audit(
            actor=actor,
            event_type=f"approval_{new_status}",
            resource_type="approval",
            resource_id=str(approval.id),
            details={
                "run_id": str(approval.run_id),
                "decision": decision,
                "reason": reason,
                "idempotency_key": idempotency_key,
            },
        )
        await self._session.commit()
        return approval

    # ── Audit ─────────────────────────────────────────────────────────

    async def get_audit_trail(
        self,
        resource_type: str,
        resource_id: str,
    ) -> list[AuditEvent]:
        """Fetch audit events for a specific resource."""
        result = await self._session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == resource_type,
                AuditEvent.resource_id == resource_id,
            )
            .order_by(AuditEvent.created_at)
        )
        return list(result.scalars().all())

    async def _audit(
        self,
        *,
        actor: str,
        event_type: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record an audit event."""
        event = AuditEvent(
            actor=actor,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            details_json=details,
        )
        self._session.add(event)
        logger.info(
            "Audit: %s %s/%s by %s",
            event_type,
            resource_type,
            resource_id,
            actor,
            extra={"structured": details},
        )


# ── Domain errors ─────────────────────────────────────────────────────


class IncidentNotFoundError(Exception):
    """Raised when an incident is not found."""


class RunNotFoundError(Exception):
    """Raised when an investigation run is not found."""


class InvalidTransitionError(Exception):
    """Raised when a status transition is not allowed."""


class ApprovalNotFoundError(Exception):
    """Raised when an approval is not found."""


class InvalidApprovalStateError(Exception):
    """Raised when an approval decision is invalid for its current state."""

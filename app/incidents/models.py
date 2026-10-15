"""Incident domain models — incidents, investigation runs, evidence, and audit.

These tables capture the incident lifecycle from creation through
investigation, approval, remediation, and resolution.  Evidence items
are immutable observations with provenance; audit events form an
append-only log of all significant actions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# ── Incident ──────────────────────────────────────────────────────────


class Incident(Base):
    """A reported or simulated service incident."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    service: Mapped[str] = mapped_column(String(100), nullable=False, default="shopapi")
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        doc="critical | high | medium | low",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="open",
        doc="open|investigating|awaiting_approval|remediating|verifying|resolved|mitigated",
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="manual",
        doc="manual | simulator",
    )
    scenario_key: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="If created by the simulator, the scenario key.",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Optimistic concurrency version counter.",
    )

    __table_args__ = (Index("ix_incidents_status_time", "status", "created_at"),)

    def __repr__(self) -> str:
        return f"<Incident {self.id} status={self.status} severity={self.severity}>"


# ── Investigation Run ─────────────────────────────────────────────────


class InvestigationRun(Base):
    """A single execution of the LangGraph investigation workflow."""

    __tablename__ = "investigation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="LangGraph thread identifier for checkpoint continuity.",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        doc="pending | running | awaiting_approval | completed | failed | cancelled",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    graph_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_runs_incident", "incident_id"),)

    def __repr__(self) -> str:
        return f"<InvestigationRun {self.id} status={self.status}>"


# ── Evidence Item ─────────────────────────────────────────────────────


class EvidenceItem(Base):
    """An immutable observation collected during investigation.

    Evidence items carry provenance (source_type, source_ref, observed_at)
    and are always tagged as simulated in this project.
    """

    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        doc="log | metric | trace | change",
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Reference to the original data source (e.g., telemetry event ID, time window).",
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulated: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        doc="Always True in this project — all evidence comes from simulation.",
    )

    __table_args__ = (Index("ix_evidence_run_type", "run_id", "source_type"),)

    def __repr__(self) -> str:
        return f"<EvidenceItem {self.id} type={self.source_type}>"


# ── Audit Event ───────────────────────────────────────────────────────


class AuditEvent(Base):
    """Append-only audit log of significant application actions."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="system",
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="e.g., incident_created, status_changed, investigation_started",
    )
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="e.g., incident, investigation_run, evidence_item",
    )
    resource_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_audit_resource", "resource_type", "resource_id"),
        Index("ix_audit_time", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditEvent {self.event_type} {self.resource_type}/{self.resource_id}>"


# ── Approval ──────────────────────────────────────────────────────────


class Approval(Base):
    """An explicit human-in-the-loop approval record for a proposed remediation action."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="e.g., disable_fault, rollback_release",
    )
    action_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        doc="pending | approved | rejected | requested_more_evidence",
    )
    risk: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="low",
        doc="low | medium | high",
    )
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        doc="Unique client-supplied key to guarantee idempotency on retry.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_approvals_run_status", "run_id", "status"),
        Index("ix_approvals_incident", "incident_id"),
    )

    def __repr__(self) -> str:
        return f"<Approval {self.id} action={self.action_type} status={self.status}>"

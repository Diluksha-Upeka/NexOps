"""Pydantic request/response schemas for the Incident API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ── Incident Schemas ──────────────────────────────────────────────────


class CreateIncidentRequest(BaseModel):
    """Request body for POST /api/v1/incidents."""

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    service: str = Field(default="shopapi", max_length=100)
    severity: str = Field(default="medium", pattern=r"^(critical|high|medium|low)$")
    source: str = Field(default="manual", pattern=r"^(manual|simulator)$")
    scenario_key: str | None = Field(default=None, max_length=100)


class IncidentResponse(BaseModel):
    """Public representation of an incident."""

    id: UUID
    title: str
    description: str
    service: str
    severity: str
    status: str
    source: str
    scenario_key: str | None
    started_at: datetime
    created_at: datetime
    resolved_at: datetime | None
    version: int

    model_config = {"from_attributes": True}


class IncidentListResponse(BaseModel):
    """Paginated list of incidents."""

    items: list[IncidentResponse]
    total: int


class ResolveIncidentRequest(BaseModel):
    """Request body for POST /api/v1/incidents/{id}/resolve."""

    reason: str = Field(min_length=1, max_length=2000)
    actor: str = Field(default="dev-user", max_length=100)


# ── Investigation Run Schemas ─────────────────────────────────────────


class InvestigationRunResponse(BaseModel):
    """Public representation of an investigation run."""

    id: UUID
    incident_id: UUID
    thread_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    model_name: str | None
    prompt_version: str | None
    graph_version: str | None
    error_code: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


# ── Evidence Schemas ──────────────────────────────────────────────────


class EvidenceItemResponse(BaseModel):
    """Public representation of an evidence item."""

    id: UUID
    run_id: UUID
    source_type: str
    observed_at: datetime
    summary: str
    payload_json: dict[str, Any] | None
    source_ref: str | None
    confidence: float | None
    simulated: bool

    model_config = {"from_attributes": True}


# ── Audit Schemas ─────────────────────────────────────────────────────


class AuditEventResponse(BaseModel):
    """Public representation of an audit event."""

    id: UUID
    actor: str
    event_type: str
    resource_type: str
    resource_id: str
    details_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Approval Schemas ──────────────────────────────────────────────────


class ApprovalResponse(BaseModel):
    """Public representation of an approval request record."""

    id: UUID
    run_id: UUID
    incident_id: UUID
    action_type: str
    action_payload: dict[str, Any] | None
    status: str
    risk: str
    reasoning: str
    actor: str | None
    decision_reason: str | None
    idempotency_key: str | None
    created_at: datetime
    decided_at: datetime | None

    model_config = {"from_attributes": True}


class SubmitApprovalRequest(BaseModel):
    """Request body for POST /api/v1/runs/{id}/approval."""

    decision: str = Field(pattern=r"^(approved|rejected|request_more_evidence)$")
    actor: str = Field(default="dev-operator", min_length=1, max_length=100)
    reason: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=100)


class RunDetailResponse(BaseModel):
    """Comprehensive investigation run detail with evidence, hypotheses, and approvals."""

    run: InvestigationRunResponse
    evidence: list[EvidenceItemResponse]
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    proposed_action: dict[str, Any] | None = None
    approval: ApprovalResponse | None = None
    is_awaiting_approval: bool = False

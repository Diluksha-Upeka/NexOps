"""Typed state and reducers for the LangGraph investigation workflow.

The state is typed with TypedDict and uses explicit reducers for
collections that receive parallel updates from concurrent evidence branches.
Large raw telemetry is kept out of state; bounded summaries and cited
references are stored instead.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any

from typing_extensions import TypedDict

# ── Typed data structures ─────────────────────────────────────────────


class Evidence(TypedDict, total=False):
    """An immutable observed piece of evidence with citation provenance."""

    id: str
    source_type: str  # "logs" | "metrics" | "traces" | "changes"
    source_ref: str  # e.g. "logs:shopapi:2026-10-12T04:00/2026-10-12T05:00"
    summary: str
    data: dict[str, Any]
    observed_at: str
    confidence: float
    simulated: bool


class InvestigationTask(TypedDict, total=False):
    """A bounded investigation task targeting a specific evidence source."""

    id: str
    branch: str  # "logs" | "metrics" | "traces" | "changes"
    query_params: dict[str, Any]
    status: str  # "pending" | "completed" | "failed"
    rationale: str


class Hypothesis(TypedDict, total=False):
    """A candidate explanation for the incident with supporting evidence citations."""

    cause_key: str  # "db_latency" | "db_connection_exhaustion" | "bad_release" | ...
    title: str
    description: str
    confidence: float  # Calibrated 0.0 to 1.0
    supporting_evidence_ids: list[str]  # IDs of cited Evidence items
    contradictions: list[str]


class Recommendation(TypedDict, total=False):
    """An allowlisted, structured remediation proposal awaiting human review."""

    action_type: str
    parameters: dict[str, Any]
    rationale: str
    risk_assessment: str
    rollback_plan: str
    verification_plan: str


class GraphError(TypedDict, total=False):
    """A structured error envelope preserving partial run state."""

    node: str
    error_code: str
    message: str
    retryable: bool


class RemediationOutcome(TypedDict, total=False):
    """Typed result of a sandbox remediation execution."""

    success: bool
    action_type: str
    idempotency_key: str
    executed_at: str
    status: str  # "success" | "denied" | "failed" | "no_op"
    details: dict[str, Any]
    denial_code: str | None
    denial_reason: str | None
    error_message: str | None
    rollback_instruction: str | None


class VerificationOutcome(TypedDict, total=False):
    """Typed result of post-action verification."""

    passed: bool
    outcome: str  # "resolved" | "mitigated" | "failed" | "inconclusive"
    checks: list[dict[str, Any]]
    summary: str
    verified_at: str
    recommended_incident_status: str


class FinalReport(TypedDict, total=False):
    """A comprehensive summary report produced at the end of the investigation."""

    incident_id: str
    run_id: str
    status: str  # "analyzed" | "insufficient_evidence" | "failed"
    primary_cause: str | None
    confidence: float
    evidence_count: int
    summary: str
    recommendation: Recommendation | None
    missing_evidence: list[str]
    remediation_result: RemediationOutcome | None
    verification_result: VerificationOutcome | None
    trace_id: str | None


# ── Reducers ──────────────────────────────────────────────────────────


def add_evidence(current: list[Evidence], new_items: list[Evidence]) -> list[Evidence]:
    """Reducer that appends new evidence items while deduplicating by id and source_ref.

    This ensures concurrent branches can safely output evidence without
    overwriting siblings or creating duplicate records across investigation rounds.
    """
    if not current:
        return list(new_items)
    if not new_items:
        return list(current)

    existing_ids = {item.get("id") for item in current if "id" in item}
    existing_refs = {item.get("source_ref") for item in current if "source_ref" in item}

    result = list(current)
    for item in new_items:
        item_id = item.get("id")
        item_ref = item.get("source_ref")
        # Deduplicate if ID or exact source_ref is already recorded
        if item_id and item_id in existing_ids:
            continue
        if item_ref and item_ref in existing_refs:
            continue
        result.append(item)
        if item_id:
            existing_ids.add(item_id)
        if item_ref:
            existing_refs.add(item_ref)

    return result


# ── Graph State ───────────────────────────────────────────────────────


class InvestigationState(TypedDict, total=False):
    """Core state for the LangGraph incident investigation workflow."""

    # Workflow identifiers
    incident_id: str
    run_id: str
    thread_id: str
    trace_id: str  # Distributed trace correlation (Phase 7)

    # Context
    incident: dict[str, Any]  # Title, description, service, severity, scenario_key

    # Investigation progression
    plan: list[InvestigationTask]
    evidence: Annotated[list[Evidence], add_evidence]
    hypotheses: list[Hypothesis]
    confidence: float
    missing_evidence: list[str]
    investigation_round: int
    max_investigation_rounds: int

    # Outcomes
    recommendation: Recommendation | None
    errors: Annotated[list[GraphError], operator.add]
    # status: "investigating" | "awaiting_approval" | "insufficient_evidence"
    #         | "remediating" | "verifying" | "completed" | "failed"
    status: str
    final_report: FinalReport | None

    # Human-in-the-loop approval
    approval_status: str | None  # "pending" | "approved" | "rejected" | "requested_more_evidence"
    approval_decision: dict[str, Any] | None

    # Phase 6: Remediation and verification results
    remediation_result: RemediationOutcome | None
    verification_result: VerificationOutcome | None

    # Metadata & Provenance
    model_name: str
    prompt_version: str
    graph_version: str

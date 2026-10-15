"""Unit tests for the LangGraph incident investigation workflow (Phase 3).

Verifies:
  - Branch fan-out and fan-in convergence
  - Reducer correctness and deduplication
  - Conditional route choices (sufficient vs needs_refinement vs insufficient)
  - Partial branch failure isolation and error envelopes
  - Maximum investigation rounds and bounded loop termination
  - Traceable evidence citations and provenance
  - Propose remediation action catalog mapping
  - Integration with the FastAPI investigation endpoints
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.graph.nodes import route_sufficiency
from app.graph.state import (
    Evidence,
    Hypothesis,
    InvestigationState,
    add_evidence,
)
from app.graph.workflow import run_investigation
from app.main import app
from app.remediation.catalog import (
    ACTION_CATALOG,
    CAUSE_TO_ACTION,
    get_action_definition,
    map_cause_to_action,
)

# ── Test 1: Reducer Correctness & Deduplication ───────────────────────


def test_add_evidence_reducer_deduplication() -> None:
    """Reducer must merge distinct items and deduplicate identical IDs/refs."""
    ev1 = Evidence(
        id="ev-1",
        source_type="metrics",
        source_ref="metrics:shopapi:request_duration:w1",
        summary="Latency high",
        data={"p95": 900},
        observed_at="2026-10-15T00:00:00Z",
        confidence=0.9,
        simulated=True,
    )
    ev2 = Evidence(
        id="ev-2",
        source_type="traces",
        source_ref="traces:shopapi:w1",
        summary="DB span slow",
        data={"span_count": 5},
        observed_at="2026-10-15T00:00:00Z",
        confidence=0.85,
        simulated=True,
    )

    # Initial append
    merged = add_evidence([], [ev1, ev2])
    assert len(merged) == 2

    # Duplicate ID append
    duplicate_id = Evidence(
        id="ev-1",
        source_type="metrics",
        source_ref="metrics:shopapi:other_ref",
        summary="Duplicate ID",
        data={},
        observed_at="2026-10-15T00:01:00Z",
        confidence=0.5,
        simulated=True,
    )
    merged_dup = add_evidence(merged, [duplicate_id])
    assert len(merged_dup) == 2

    # Duplicate source_ref append
    duplicate_ref = Evidence(
        id="ev-3",
        source_type="traces",
        source_ref="traces:shopapi:w1",
        summary="Duplicate Ref",
        data={},
        observed_at="2026-10-15T00:01:00Z",
        confidence=0.5,
        simulated=True,
    )
    merged_ref = add_evidence(merged, [duplicate_ref])
    assert len(merged_ref) == 2

    # Brand new distinct item append
    ev3 = Evidence(
        id="ev-4",
        source_type="logs",
        source_ref="logs:shopapi:w1",
        summary="Logs normal",
        data={},
        observed_at="2026-10-15T00:02:00Z",
        confidence=0.8,
        simulated=True,
    )
    merged_new = add_evidence(merged, [ev3])
    assert len(merged_new) == 3


# ── Test 2: Branch Fan-out and Fan-in ─────────────────────────────────


@pytest.mark.asyncio
async def test_branch_fan_out_and_fan_in() -> None:
    """Graph must fan out to all 4 evidence branches and fan in at synthesis."""
    incident: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "title": "ShopAPI latency degradation",
        "description": "p95 latency exceeded 1200ms",
        "service": "shopapi",
        "severity": "high",
        "scenario_key": "db_latency",
    }

    result = await run_investigation(incident, max_rounds=1)

    assert result["status"] in ("awaiting_approval", "insufficient_evidence")
    assert "evidence" in result
    evidence = result["evidence"]

    # All branches ran and added evidence
    source_types = {e["source_type"] for e in evidence}
    assert "logs" in source_types
    assert "metrics" in source_types
    assert "traces" in source_types
    assert "changes" in source_types


# ── Test 3: Route Choices — Sufficient Evidence ───────────────────────


@pytest.mark.asyncio
async def test_route_choices_sufficient_evidence() -> None:
    """When confidence is high with supporting citations, route to remediation."""
    incident: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "title": "High latency on ShopAPI product queries",
        "description": "Database query duration causing p95 spike to 1.4s",
        "service": "shopapi",
        "severity": "critical",
        "scenario_key": "db_latency",
    }

    result = await run_investigation(incident, max_rounds=2)

    assert result["status"] == "awaiting_approval"
    assert result["confidence"] >= 0.70

    recommendation = result.get("recommendation")
    assert recommendation is not None
    assert recommendation["action_type"] == "disable_fault"
    assert recommendation["parameters"]["scenario_key"] == "db_latency"
    assert "verification_plan" in recommendation
    assert "rollback_plan" in recommendation


# ── Test 4: Route Choices — Insufficient Evidence at Limit ────────────


@pytest.mark.asyncio
async def test_route_choices_insufficient_evidence() -> None:
    """When evidence is inconclusive and max rounds reached, route to insufficient report."""
    state: InvestigationState = {
        "confidence": 0.35,
        "investigation_round": 2,
        "max_investigation_rounds": 2,
        "hypotheses": [
            Hypothesis(
                cause_key="unknown",
                title="Inconclusive Telemetry Findings",
                description="Ambiguous telemetry",
                confidence=0.35,
                supporting_evidence_ids=[],
                contradictions=[],
            )
        ],
    }

    decision = route_sufficiency(state)
    assert decision == "insufficient"


# ── Test 5: Route Choices — Refinement Loop ───────────────────────────


@pytest.mark.asyncio
async def test_route_choices_refinement_loop() -> None:
    """When confidence is low but budget remains, route to refine_plan."""
    state: InvestigationState = {
        "confidence": 0.40,
        "investigation_round": 1,
        "max_investigation_rounds": 2,
        "hypotheses": [
            Hypothesis(
                cause_key="unknown",
                title="Ambiguous findings",
                description="Single weak signal",
                confidence=0.40,
                supporting_evidence_ids=["ev-1"],
                contradictions=[],
            )
        ],
    }

    decision = route_sufficiency(state)
    assert decision == "needs_refinement"


# ── Test 6: Bounded Refinement Cycle & Max Rounds ─────────────────────


@pytest.mark.asyncio
async def test_bounded_refinement_cycle_max_rounds() -> None:
    """Graph must respect max_investigation_rounds and terminate cleanly."""
    incident: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "title": "Ambiguous intermittent warning",
        "description": "Routine minor jitter without clear pattern",
        "service": "shopapi",
        "severity": "low",
        "scenario_key": None,
    }

    result = await run_investigation(incident, max_rounds=2)

    # Investigation must conclude at round 2
    assert result["investigation_round"] == 2
    assert result["max_investigation_rounds"] == 2
    assert result["final_report"] is not None


# ── Test 7: Partial Branch Failure Isolation ──────────────────────────


@pytest.mark.asyncio
async def test_partial_branch_failure_isolation() -> None:
    """A single branch failure must not abort sibling branches or crash the graph."""
    incident: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "title": "ShopAPI p95 latency spike",
        "description": "Investigating with trace collector unavailable",
        "service": "shopapi",
        "severity": "high",
        "scenario_key": "db_latency",
    }

    # Simulate traces branch failing
    result = await run_investigation(
        incident,
        max_rounds=1,
        mock_errors={"mock_traces_error": "Connection timed out to trace backend"},
    )

    # Graph still completed!
    assert result["status"] in ("awaiting_approval", "insufficient_evidence")

    # The error envelope was captured
    errors = result.get("errors", [])
    assert any(e.get("node") == "investigate_traces" for e in errors)
    assert any("timed out" in e.get("message", "") for e in errors)

    # Other branches still succeeded and provided evidence
    source_types = {e["source_type"] for e in result.get("evidence", [])}
    assert "logs" in source_types
    assert "metrics" in source_types
    assert "changes" in source_types


# ── Test 8: Traceable Evidence IDs and Provenance ─────────────────────


@pytest.mark.asyncio
async def test_traceable_evidence_ids_and_provenance() -> None:
    """Hypotheses must cite actual Evidence item IDs and valid source_ref strings."""
    incident: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "title": "ShopAPI latency alert",
        "description": "P95 latency degradation observed",
        "service": "shopapi",
        "severity": "high",
        "scenario_key": "db_latency",
    }

    result = await run_investigation(incident, max_rounds=1)
    evidence_items = result.get("evidence", [])
    evidence_ids = {e["id"] for e in evidence_items if "id" in e}

    # Verify all evidence items have valid source_ref provenance
    for item in evidence_items:
        assert item.get("source_ref") is not None
        assert ":" in item["source_ref"]
        assert item.get("simulated") is True

    # Verify cited evidence IDs point to actual evidence
    hypotheses = result.get("hypotheses", [])
    for hyp in hypotheses:
        for cited_id in hyp.get("supporting_evidence_ids", []):
            assert cited_id in evidence_ids, f"Cited ID {cited_id} not in evidence collection"


# ── Test 9: No Unsupported Causes in Fixtures ─────────────────────────


@pytest.mark.asyncio
async def test_no_unsupported_causes_in_fixtures() -> None:
    """Graph must never invent an unsupported cause without corroborating evidence."""
    incident: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "title": "ShopAPI general health check",
        "description": "Baseline monitoring without injected faults",
        "service": "shopapi",
        "severity": "low",
        "scenario_key": None,
    }

    result = await run_investigation(incident, max_rounds=1)
    hypotheses: list[Hypothesis] = result.get("hypotheses", [])
    assert len(hypotheses) > 0
    top_hyp = hypotheses[0]

    # Without high latency or pool errors or bad releases, it should not diagnose them
    if not any(e.get("data", {}).get("latency_degraded") for e in result.get("evidence", [])):
        assert top_hyp.get("cause_key") != "db_latency"
        assert top_hyp.get("cause_key") != "bad_release"


# ── Test 10: Action Catalog Mapping ───────────────────────────────────


def test_action_catalog_mapping() -> None:
    """Catalog must strictly define parameters, risk levels, and rollback plans."""
    assert "disable_fault" in ACTION_CATALOG
    assert "rollback_release" in ACTION_CATALOG
    assert "scale_pool" in ACTION_CATALOG

    # Verify cause mappings
    for cause in ("db_latency", "db_connection_exhaustion", "dependency_timeout", "elevated_5xx"):
        assert cause in CAUSE_TO_ACTION
        action = map_cause_to_action(cause)
        assert action is not None
        assert action["action_type"] in ACTION_CATALOG
        assert action["risk_level"] in ("low", "medium", "high")
        assert "verification_plan" in action

    # Unknown cause returns None
    assert map_cause_to_action("unknown_cause_xyz") is None
    assert get_action_definition("non_existent_action") is None


# ── Test 11: API Integration — Start Investigation & Persist Evidence ─


@pytest.mark.asyncio
async def test_api_investigation_lifecycle() -> None:
    """POST /incidents/{id}/investigations executes the workflow and persists evidence."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create an incident
        create_res = await client.post(
            "/api/v1/incidents",
            json={
                "title": "ShopAPI DB Latency Test",
                "description": "P95 latency elevated to 1.2s",
                "service": "shopapi",
                "severity": "high",
                "scenario_key": "db_latency",
            },
        )
        assert create_res.status_code == 201
        incident_id = create_res.json()["id"]

        # 2. Start investigation run
        investigate_res = await client.post(f"/api/v1/incidents/{incident_id}/investigations")
        assert investigate_res.status_code == 202
        run_data = investigate_res.json()
        run_id = run_data["id"]
        assert run_data["incident_id"] == incident_id
        assert run_data["status"] in ("awaiting_approval", "completed")

        # 3. Retrieve run by ID
        get_run_res = await client.get(f"/api/v1/runs/{run_id}")
        assert get_run_res.status_code == 200
        assert get_run_res.json()["id"] == run_id

        # 4. Retrieve persisted evidence items
        evidence_res = await client.get(f"/api/v1/runs/{run_id}/evidence")
        assert evidence_res.status_code == 200
        evidence_list = evidence_res.json()
        assert len(evidence_list) > 0
        for ev in evidence_list:
            assert ev["run_id"] == run_id
            assert ev["simulated"] is True
            assert ev["source_ref"] is not None

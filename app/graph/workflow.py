"""LangGraph StateGraph workflow definition for incident investigation.

Wires:
  load_incident -> triage -> plan_investigation
  -> [investigate_logs, investigate_metrics, investigate_traces, investigate_changes] (Fan-out)
  -> synthesize_evidence (Fan-in)
  -> analyze_root_cause
  -> route_sufficiency:
       "sufficient"        -> propose_remediation -> finalize -> END
       "needs_refinement"  -> refine_plan -> [evidence branches...] (Bounded loop)
       "insufficient"      -> insufficient_evidence_report -> finalize -> END
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes import (
    analyze_root_cause_node,
    finalize_node,
    insufficient_evidence_report_node,
    investigate_changes_node,
    investigate_logs_node,
    investigate_metrics_node,
    investigate_traces_node,
    load_incident_node,
    plan_investigation_node,
    propose_remediation_node,
    refine_plan_node,
    route_sufficiency,
    synthesize_evidence_node,
    triage_node,
)
from app.graph.state import InvestigationState


def build_investigation_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Construct and compile the LangGraph incident investigation workflow.

    Defaults to an in-memory checkpointer (MemorySaver) for Phase 3
    deterministic tests and local fast development.
    """
    workflow = StateGraph(InvestigationState)

    # 1. Pipeline entry and planning nodes
    workflow.add_node("load_incident", load_incident_node)
    workflow.add_node("triage", triage_node)
    workflow.add_node("plan_investigation", plan_investigation_node)

    # 2. Parallel evidence branch nodes
    workflow.add_node("investigate_logs", investigate_logs_node)
    workflow.add_node("investigate_metrics", investigate_metrics_node)
    workflow.add_node("investigate_traces", investigate_traces_node)
    workflow.add_node("investigate_changes", investigate_changes_node)

    # 3. Fan-in synthesis and root cause analysis
    workflow.add_node("synthesize_evidence", synthesize_evidence_node)
    workflow.add_node("analyze_root_cause", analyze_root_cause_node)

    # 4. Refinement and termination nodes
    workflow.add_node("refine_plan", refine_plan_node)
    workflow.add_node("propose_remediation", propose_remediation_node)
    workflow.add_node("insufficient_evidence_report", insufficient_evidence_report_node)
    workflow.add_node("finalize", finalize_node)

    # ── Edges ─────────────────────────────────────────────────────────

    workflow.set_entry_point("load_incident")
    workflow.add_edge("load_incident", "triage")
    workflow.add_edge("triage", "plan_investigation")

    # Fan-out: plan_investigation initiates parallel branches
    workflow.add_edge("plan_investigation", "investigate_logs")
    workflow.add_edge("plan_investigation", "investigate_metrics")
    workflow.add_edge("plan_investigation", "investigate_traces")
    workflow.add_edge("plan_investigation", "investigate_changes")

    # Fan-in: all parallel branches converge at synthesize_evidence
    workflow.add_edge("investigate_logs", "synthesize_evidence")
    workflow.add_edge("investigate_metrics", "synthesize_evidence")
    workflow.add_edge("investigate_traces", "synthesize_evidence")
    workflow.add_edge("investigate_changes", "synthesize_evidence")

    workflow.add_edge("synthesize_evidence", "analyze_root_cause")

    # Conditional routing based on evidence sufficiency & calibrated confidence
    workflow.add_conditional_edges(
        "analyze_root_cause",
        route_sufficiency,
        {
            "sufficient": "propose_remediation",
            "needs_refinement": "refine_plan",
            "insufficient": "insufficient_evidence_report",
        },
    )

    # Bounded refinement loop: refine_plan re-executes evidence branches
    workflow.add_edge("refine_plan", "investigate_logs")
    workflow.add_edge("refine_plan", "investigate_metrics")
    workflow.add_edge("refine_plan", "investigate_traces")
    workflow.add_edge("refine_plan", "investigate_changes")

    # Finalize and exit
    workflow.add_edge("propose_remediation", "finalize")
    workflow.add_edge("insufficient_evidence_report", "finalize")
    workflow.add_edge("finalize", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return workflow.compile(checkpointer=saver)


# Shared compiled graph instance for application execution
_default_graph: CompiledStateGraph[Any, Any, Any, Any] | None = None


def get_investigation_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """Return singleton instance of the compiled investigation graph."""
    global _default_graph
    if _default_graph is None:
        _default_graph = build_investigation_graph()
    return _default_graph


async def run_investigation(
    incident: dict[str, Any],
    *,
    incident_id: str | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    max_rounds: int = 2,
    session: Any = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    mock_errors: dict[str, str] | None = None,
) -> InvestigationState:
    """Execute the investigation workflow asynchronously and return the final state."""
    graph = (
        build_investigation_graph(checkpointer=checkpointer)
        if checkpointer
        else get_investigation_graph()
    )

    resolved_incident_id = incident_id or str(incident.get("id") or uuid.uuid4())
    resolved_run_id = run_id or str(uuid.uuid4())
    resolved_thread_id = thread_id or f"thread-{resolved_run_id[:12]}"

    initial_state: InvestigationState = {
        "incident_id": resolved_incident_id,
        "run_id": resolved_run_id,
        "thread_id": resolved_thread_id,
        "incident": incident,
        "max_investigation_rounds": max_rounds,
        "investigation_round": 1,
        "status": "investigating",
        "evidence": [],
        "errors": [],
        "hypotheses": [],
        "confidence": 0.0,
        "missing_evidence": [],
    }

    configurable: dict[str, Any] = {
        "thread_id": resolved_thread_id,
        "session": session,
    }
    if mock_errors:
        configurable.update(mock_errors)

    config: RunnableConfig = {
        "configurable": configurable,
        "recursion_limit": 30,
    }

    result = await graph.ainvoke(initial_state, config=config)
    return cast(InvestigationState, result)

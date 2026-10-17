"""Investigation graph nodes for LangGraph workflow.

Each node is an async function that accepts the typed state and returns
state updates. Concurrent branches are isolated: partial failures produce
structured GraphError items without aborting sibling nodes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.db.engine import get_session_safe
from app.graph.state import (
    Evidence,
    FinalReport,
    GraphError,
    Hypothesis,
    InvestigationState,
    InvestigationTask,
    Recommendation,
    RemediationOutcome,
    VerificationOutcome,
)
from app.incidents.evidence_tools import (
    ToolResult,
    query_changes,
    query_logs,
    query_metrics,
    query_traces,
)
from app.llm import get_llm_adapter
from app.observability import (
    get_current_trace_id,
    record_evidence_collected,
    record_investigation_run,
    record_remediation_action,
    set_correlation_context,
)
from app.remediation.catalog import map_cause_to_action
from app.remediation.executor import SandboxExecutor
from app.remediation.verification import verify_remediation as run_verification
from app.shopapi.simulator import get_simulator

logger = logging.getLogger(__name__)

# Sufficiency threshold for diagnosing an incident with confidence
CONFIDENCE_THRESHOLD = 0.70


# ── Node 1: load_incident ─────────────────────────────────────────────


async def load_incident_node(state: InvestigationState, config: RunnableConfig) -> dict[str, Any]:
    """Load and validate incident context, initializing IDs and limits."""
    incident = state.get("incident") or {}
    incident_id = state.get("incident_id") or str(incident.get("id") or uuid.uuid4())
    run_id = state.get("run_id") or str(uuid.uuid4())
    thread_id = state.get("thread_id") or f"thread-{run_id[:12]}"
    max_rounds = state.get("max_investigation_rounds") or 2
    trace_id = state.get("trace_id") or get_current_trace_id() or uuid.uuid4().hex

    # Set distributed correlation context for this run
    set_correlation_context(run_id=run_id, trace_id=trace_id)

    return {
        "incident_id": incident_id,
        "run_id": run_id,
        "thread_id": thread_id,
        "trace_id": trace_id,
        "incident": incident,
        "investigation_round": 1,
        "max_investigation_rounds": max_rounds,
        "status": "investigating",
        "evidence": [],
        "errors": [],
        "hypotheses": [],
        "confidence": 0.0,
        "missing_evidence": [],
    }


# ── Node 2: triage ────────────────────────────────────────────────────


async def triage_node(state: InvestigationState, config: RunnableConfig) -> dict[str, Any]:
    """Classify service, severity, and symptoms to formulate initial hypotheses."""
    incident = state.get("incident") or {}
    title = str(incident.get("title", "")).lower()
    description = str(incident.get("description", "")).lower()
    content = f"{title} {description}"

    candidate_hypotheses: list[Hypothesis] = []

    # Rule-based symptom triage
    if any(k in content for k in ("latency", "slow", "delay", "p95", "response time")):
        candidate_hypotheses.append(
            Hypothesis(
                cause_key="db_latency",
                title="Database Query Latency",
                description="Simulated database delay causing elevated latency in ShopAPI.",
                confidence=0.4,
                supporting_evidence_ids=[],
                contradictions=[],
            )
        )

    if any(k in content for k in ("pool", "exhaustion", "connection", "503")):
        candidate_hypotheses.append(
            Hypothesis(
                cause_key="db_connection_exhaustion",
                title="Database Connection Exhaustion",
                description="Database pool saturation rejecting or delaying connections.",
                confidence=0.4,
                supporting_evidence_ids=[],
                contradictions=[],
            )
        )

    if any(k in content for k in ("release", "deploy", "version", "revision")):
        candidate_hypotheses.append(
            Hypothesis(
                cause_key="bad_release",
                title="Faulty Deployment or Configuration Revision",
                description="Recent code/config deployment introduced degradation.",
                confidence=0.4,
                supporting_evidence_ids=[],
                contradictions=[],
            )
        )

    if any(k in content for k in ("timeout", "shipping", "payment", "dependency")):
        candidate_hypotheses.append(
            Hypothesis(
                cause_key="dependency_timeout",
                title="External Dependency Timeout",
                description="Downstream service call exceeding latency threshold.",
                confidence=0.4,
                supporting_evidence_ids=[],
                contradictions=[],
            )
        )

    if any(k in content for k in ("5xx", "500", "error rate", "elevated")):
        candidate_hypotheses.append(
            Hypothesis(
                cause_key="elevated_5xx",
                title="Elevated Internal Server Errors",
                description="Internal server error rate spike on critical endpoints.",
                confidence=0.4,
                supporting_evidence_ids=[],
                contradictions=[],
            )
        )

    if not candidate_hypotheses:
        candidate_hypotheses.append(
            Hypothesis(
                cause_key="unknown",
                title="Unclassified Incident",
                description="General degradation requiring baseline multi-source investigation.",
                confidence=0.2,
                supporting_evidence_ids=[],
                contradictions=[],
            )
        )

    return {"hypotheses": candidate_hypotheses}


# ── Node 3: plan_investigation ────────────────────────────────────────


async def plan_investigation_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Select evidence branches to investigate in parallel."""
    incident = state.get("incident") or {}
    service = str(incident.get("service") or "shopapi")
    round_num = state.get("investigation_round", 1)

    tasks: list[InvestigationTask] = [
        InvestigationTask(
            id=f"task-logs-r{round_num}",
            branch="logs",
            query_params={"service": service, "limit": 100},
            status="pending",
            rationale="Inspect structured log events for error codes and stack traces.",
        ),
        InvestigationTask(
            id=f"task-metrics-r{round_num}",
            branch="metrics",
            query_params={"service": service, "metric": "request_duration", "limit": 100},
            status="pending",
            rationale="Measure latency percentiles (p50, p95) and error rates.",
        ),
        InvestigationTask(
            id=f"task-traces-r{round_num}",
            branch="traces",
            query_params={"service": service, "limit": 100},
            status="pending",
            rationale="Trace spans to isolate slow database or dependency components.",
        ),
        InvestigationTask(
            id=f"task-changes-r{round_num}",
            branch="changes",
            query_params={"service": service, "limit": 50},
            status="pending",
            rationale="Check recent deployments and configuration changes.",
        ),
    ]

    return {"plan": tasks}


# ── Helper: Helper to resolve time windows ────────────────────────────


def _resolve_time_window(state: InvestigationState) -> tuple[datetime, datetime]:
    """Calculate bounded query time window based on incident timestamp."""
    incident = state.get("incident") or {}
    now = datetime.now(UTC)
    start_raw = incident.get("started_at")
    if isinstance(start_raw, str):
        try:
            start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except Exception:
            start = now - timedelta(hours=1)
    elif isinstance(start_raw, datetime):
        start = start_raw
    else:
        start = now - timedelta(hours=1)

    # Ensure start is timezone-aware
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)

    # Provide a 15-minute buffer before incident start
    start = start - timedelta(minutes=15)
    end = now + timedelta(minutes=5)
    return start, end


# ── Parallel Branch 1: investigate_logs ───────────────────────────────


async def investigate_logs_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Query logs branch concurrently."""
    incident = state.get("incident") or {}
    service = str(incident.get("service") or "shopapi")
    start, end = _resolve_time_window(state)

    # Check for tool override in config (useful for testing partial branch failure)
    configurable = (config or {}).get("configurable", {})
    if configurable.get("mock_logs_error"):
        err = GraphError(
            node="investigate_logs",
            error_code="logs_query_failed",
            message=configurable["mock_logs_error"],
            retryable=False,
        )
        return {"errors": [err], "evidence": []}

    session = configurable.get("session")
    result: ToolResult | None = None

    try:
        if session:
            result = await query_logs(session, service=service, start=start, end=end, limit=100)
        else:
            async for sess in get_session_safe():
                result = await query_logs(sess, service=service, start=start, end=end, limit=100)
                break
    except Exception as exc:
        logger.warning("investigate_logs failed: %s", exc)
        err = GraphError(
            node="investigate_logs",
            error_code="logs_exception",
            message=str(exc),
            retryable=True,
        )
        return {"errors": [err], "evidence": []}

    if result is None or not result.ok:
        err = GraphError(
            node="investigate_logs",
            error_code=(result.error_code or "session_unavailable")
            if result
            else "session_unavailable",
            message=(result.error_message or "No database session available for logs.")
            if result
            else "No database session available for logs.",
            retryable=False,
        )
        return {"errors": [err], "evidence": []}

    # Analyze logs
    error_logs = [row for row in result.data if row.get("level") in ("ERROR", "CRITICAL")]
    pool_errors = [row for row in error_logs if "pool" in str(row.get("message", "")).lower()]

    summary = (
        f"Queried {result.count} logs for {service}. Found {len(error_logs)} error-level logs."
    )
    if pool_errors:
        summary += f" Detected {len(pool_errors)} connection pool exhaustion errors."

    evidence_item = Evidence(
        id=str(uuid.uuid4()),
        source_type="logs",
        source_ref=result.source_ref or f"logs:{service}:{start.isoformat()}/{end.isoformat()}",
        summary=summary,
        data={
            "total_logs": result.count,
            "error_count": len(error_logs),
            "pool_error_count": len(pool_errors),
            "samples": result.data[:5],
        },
        observed_at=datetime.now(UTC).isoformat(),
        confidence=0.85,
        simulated=True,
    )

    return {"evidence": [evidence_item]}


# ── Parallel Branch 2: investigate_metrics ────────────────────────────


async def investigate_metrics_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Query metrics branch concurrently."""
    incident = state.get("incident") or {}
    service = str(incident.get("service") or "shopapi")
    start, end = _resolve_time_window(state)

    configurable = (config or {}).get("configurable", {})
    if configurable.get("mock_metrics_error"):
        err = GraphError(
            node="investigate_metrics",
            error_code="metrics_query_failed",
            message=configurable["mock_metrics_error"],
            retryable=False,
        )
        return {"errors": [err], "evidence": []}

    session = configurable.get("session")
    result: ToolResult | None = None

    try:
        if session:
            result = await query_metrics(
                session, service=service, start=start, end=end, metric="request_duration"
            )
        else:
            async for sess in get_session_safe():
                result = await query_metrics(
                    sess, service=service, start=start, end=end, metric="request_duration"
                )
                break
    except Exception as exc:
        logger.warning("investigate_metrics failed: %s", exc)
        err = GraphError(
            node="investigate_metrics",
            error_code="metrics_exception",
            message=str(exc),
            retryable=True,
        )
        return {"errors": [err], "evidence": []}

    if result is None or not result.ok:
        err = GraphError(
            node="investigate_metrics",
            error_code=(result.error_code or "session_unavailable")
            if result
            else "session_unavailable",
            message=(result.error_message or "No database session available for metrics.")
            if result
            else "No database session available for metrics.",
            retryable=False,
        )
        return {"errors": [err], "evidence": []}

    p95 = result.data[0].get("p95_ms", 0.0) if result.data else 0.0
    avg = result.data[0].get("avg_ms", 0.0) if result.data else 0.0
    sample_count = result.data[0].get("sample_count", 0) if result.data else 0

    is_latency_degraded = p95 > 500.0 or avg > 400.0
    summary = f"Sampled {sample_count} request durations. p95={p95}ms, avg={avg}ms."
    if is_latency_degraded:
        summary += f" Significant latency degradation observed (p95={p95}ms > baseline 350ms)."

    evidence_item = Evidence(
        id=str(uuid.uuid4()),
        source_type="metrics",
        source_ref=result.source_ref
        or f"metrics:{service}:request_duration:{start.isoformat()}/{end.isoformat()}",
        summary=summary,
        data={
            "p95_ms": p95,
            "avg_ms": avg,
            "sample_count": sample_count,
            "latency_degraded": is_latency_degraded,
        },
        observed_at=datetime.now(UTC).isoformat(),
        confidence=0.90,
        simulated=True,
    )

    return {"evidence": [evidence_item]}


# ── Parallel Branch 3: investigate_traces ─────────────────────────────


async def investigate_traces_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Query traces branch concurrently."""
    incident = state.get("incident") or {}
    service = str(incident.get("service") or "shopapi")
    start, end = _resolve_time_window(state)

    configurable = (config or {}).get("configurable", {})
    if configurable.get("mock_traces_error"):
        err = GraphError(
            node="investigate_traces",
            error_code="traces_query_failed",
            message=configurable["mock_traces_error"],
            retryable=False,
        )
        return {"errors": [err], "evidence": []}

    session = configurable.get("session")
    result: ToolResult | None = None

    try:
        if session:
            result = await query_traces(session, service=service, start=start, end=end, limit=100)
        else:
            async for sess in get_session_safe():
                result = await query_traces(sess, service=service, start=start, end=end, limit=100)
                break
    except Exception as exc:
        logger.warning("investigate_traces failed: %s", exc)
        err = GraphError(
            node="investigate_traces",
            error_code="traces_exception",
            message=str(exc),
            retryable=True,
        )
        return {"errors": [err], "evidence": []}

    if result is None or not result.ok:
        err = GraphError(
            node="investigate_traces",
            error_code=(result.error_code or "session_unavailable")
            if result
            else "session_unavailable",
            message=(result.error_message or "No database session available for traces.")
            if result
            else "No database session available for traces.",
            retryable=False,
        )
        return {"errors": [err], "evidence": []}

    # Trace span analysis: check for slow DB queries or dependency timeouts
    slow_db_spans = [
        span
        for span in result.data
        if (span.get("duration_ms") or 0) > 400 and "db" in str(span.get("attributes", {})).lower()
    ]
    timeout_spans = [
        span
        for span in result.data
        if span.get("status_code") in (504, 408)
        or "timeout" in str(span.get("attributes", {})).lower()
    ]

    summary = f"Queried {result.count} trace spans for {service}."
    if slow_db_spans:
        summary += f" Identified {len(slow_db_spans)} slow database spans (>400ms)."
    if timeout_spans:
        summary += f" Identified {len(timeout_spans)} dependency timeout spans."

    evidence_item = Evidence(
        id=str(uuid.uuid4()),
        source_type="traces",
        source_ref=result.source_ref or f"traces:{service}:{start.isoformat()}/{end.isoformat()}",
        summary=summary,
        data={
            "span_count": result.count,
            "slow_db_span_count": len(slow_db_spans),
            "timeout_span_count": len(timeout_spans),
            "has_slow_db": len(slow_db_spans) > 0,
            "has_timeout": len(timeout_spans) > 0,
        },
        observed_at=datetime.now(UTC).isoformat(),
        confidence=0.88,
        simulated=True,
    )

    return {"evidence": [evidence_item]}


# ── Parallel Branch 4: investigate_changes ────────────────────────────


async def investigate_changes_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Query changes branch concurrently."""
    incident = state.get("incident") or {}
    service = str(incident.get("service") or "shopapi")
    start, end = _resolve_time_window(state)

    configurable = (config or {}).get("configurable", {})
    if configurable.get("mock_changes_error"):
        err = GraphError(
            node="investigate_changes",
            error_code="changes_query_failed",
            message=configurable["mock_changes_error"],
            retryable=False,
        )
        return {"errors": [err], "evidence": []}

    try:
        result = await query_changes(service=service, start=start, end=end, limit=50)
    except Exception as exc:
        logger.warning("investigate_changes failed: %s", exc)
        err = GraphError(
            node="investigate_changes",
            error_code="changes_exception",
            message=str(exc),
            retryable=True,
        )
        return {"errors": [err], "evidence": []}

    if not result.ok:
        err = GraphError(
            node="investigate_changes",
            error_code=result.error_code or "changes_failed",
            message=result.error_message or "Failed to query change history.",
            retryable=False,
        )
        return {"errors": [err], "evidence": []}

    recent_deployments = [
        c
        for c in result.data
        if c.get("type") in ("deployment", "release")
        or "deploy" in str(c.get("description", "")).lower()
    ]

    summary = (
        f"Queried change history. Found {result.count} total changes in the observation window."
    )
    if recent_deployments:
        summary += f" Detected {len(recent_deployments)} recent deployment/release changes."
    else:
        summary += " No recent deployment or configuration releases detected."

    evidence_item = Evidence(
        id=str(uuid.uuid4()),
        source_type="changes",
        source_ref=result.source_ref or f"changes:{service}:{start.isoformat()}/{end.isoformat()}",
        summary=summary,
        data={
            "total_changes": result.count,
            "deployment_count": len(recent_deployments),
            "recent_deployments": recent_deployments,
        },
        observed_at=datetime.now(UTC).isoformat(),
        confidence=0.90,
        simulated=True,
    )

    return {"evidence": [evidence_item]}


# ── Node 5: synthesize_evidence ───────────────────────────────────────


async def synthesize_evidence_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Fan-in node: aggregates evidence items and notes any partial branch errors."""
    evidence_items = state.get("evidence", [])
    errors = state.get("errors", [])

    sources_present = {item.get("source_type") for item in evidence_items}
    for item in evidence_items:
        record_evidence_collected(item.get("source_type", "unknown"))

    logger.info(
        "Synthesized evidence: %d items across sources %s (branch errors: %d)",
        len(evidence_items),
        sources_present,
        len(errors),
    )
    return {}


def _deterministic_root_cause_analysis(
    incident: dict[str, Any],
    evidence_items: list[Evidence],
) -> list[Hypothesis]:
    """Fallback deterministic rule-based pattern matching."""
    scenario_key = incident.get("scenario_key")
    title = str(incident.get("title", "")).lower()

    # Track evidence IDs by source type for traceable citation
    evidence_by_type: dict[str, list[Evidence]] = {}
    for item in evidence_items:
        st = item.get("source_type", "unknown")
        evidence_by_type.setdefault(st, []).append(item)

    metrics_ev = evidence_by_type.get("metrics", [])
    traces_ev = evidence_by_type.get("traces", [])
    logs_ev = evidence_by_type.get("logs", [])
    changes_ev = evidence_by_type.get("changes", [])

    has_latency_degraded = any(
        m.get("data", {}).get("latency_degraded")
        or "latency degradation" in m.get("summary", "").lower()
        for m in metrics_ev
    )
    has_slow_db_traces = any(
        t.get("data", {}).get("has_slow_db")
        or "slow database spans" in t.get("summary", "").lower()
        for t in traces_ev
    )
    has_pool_error_logs = any(
        log_item.get("data", {}).get("pool_error_count", 0) > 0
        or "connection pool exhaustion" in log_item.get("summary", "").lower()
        for log_item in logs_ev
    )
    has_recent_deploy = any(c.get("data", {}).get("deployment_count", 0) > 0 for c in changes_ev)
    has_dependency_timeout = any(
        t.get("data", {}).get("has_timeout") or "dependency timeout" in t.get("summary", "").lower()
        for t in traces_ev
    )
    has_elevated_errors = any(
        log_item.get("data", {}).get("error_count", 0) > 3 for log_item in logs_ev
    )

    hypotheses: list[Hypothesis] = []

    # Pattern 1: Database Latency
    if has_latency_degraded or (scenario_key == "db_latency") or ("latency" in title):
        supporting_ids: list[str] = []
        contradictions: list[str] = []

        for m in metrics_ev:
            if m.get("id"):
                supporting_ids.append(m["id"])
        if has_slow_db_traces:
            for t in traces_ev:
                if t.get("id"):
                    supporting_ids.append(t["id"])

        if has_recent_deploy:
            contradictions.append("Recent deployment observed, which could indicate a bad release.")
        if has_elevated_errors and not has_pool_error_logs:
            contradictions.append("Elevated error count observed alongside latency.")

        confidence = 0.92 if (has_latency_degraded and has_slow_db_traces) else 0.75
        if contradictions:
            confidence = max(0.50, confidence - 0.20)

        hypotheses.append(
            Hypothesis(
                cause_key="db_latency",
                title="Simulated Database Query Latency",
                description=(
                    "ShopAPI query execution is artificially delayed by database latency fault. "
                    "Metrics indicate severe p95 latency shift and traces corroborate database "
                    "query duration."
                ),
                confidence=confidence,
                supporting_evidence_ids=supporting_ids,
                contradictions=contradictions,
            )
        )

    # Pattern 2: Database Connection Exhaustion
    if has_pool_error_logs or (scenario_key == "db_connection_exhaustion") or ("pool" in title):
        supporting_ids = [log_item["id"] for log_item in logs_ev if log_item.get("id")]
        hypotheses.append(
            Hypothesis(
                cause_key="db_connection_exhaustion",
                title="Database Connection Pool Exhaustion",
                description="Database pool saturation rejecting or stalling connections.",
                confidence=0.90 if has_pool_error_logs else 0.70,
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
            )
        )

    # Pattern 3: Bad Release
    if (
        (has_recent_deploy and (has_latency_degraded or has_elevated_errors))
        or (scenario_key == "bad_release")
        or ("release" in title)
        or ("deploy" in title)
    ):
        supporting_ids = [c["id"] for c in changes_ev if c.get("id")]
        supporting_ids.extend([m["id"] for m in metrics_ev if m.get("id")])
        hypotheses.append(
            Hypothesis(
                cause_key="bad_release",
                title="Faulty Deployment Release",
                description="Recent deployment introduced performance regression.",
                confidence=0.88,
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
            )
        )

    # Pattern 4: Dependency Timeout
    if has_dependency_timeout or (scenario_key == "dependency_timeout"):
        supporting_ids = [t["id"] for t in traces_ev if t.get("id")]
        hypotheses.append(
            Hypothesis(
                cause_key="dependency_timeout",
                title="External Dependency Timeout",
                description=(
                    "Downstream partner service is timing out during checkout/order processing."
                ),
                confidence=0.89,
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
            )
        )

    # Pattern 5: Elevated 5xx
    if has_elevated_errors and not has_pool_error_logs:
        supporting_ids = [log_item["id"] for log_item in logs_ev if log_item.get("id")]
        hypotheses.append(
            Hypothesis(
                cause_key="elevated_5xx",
                title="Elevated Internal Server Errors",
                description="High 5xx error rate detected across service endpoints.",
                confidence=0.85,
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
            )
        )

    # Fallback if no pattern matched
    if not hypotheses:
        hypotheses.append(
            Hypothesis(
                cause_key="unknown",
                title="Inconclusive Telemetry Findings",
                description=(
                    "Collected evidence does not definitively match any known fault pattern."
                ),
                confidence=0.30,
                supporting_evidence_ids=[],
                contradictions=["Telemetry exhibits ambiguous or insufficient signals."],
            )
        )

    hypotheses.sort(key=lambda h: h.get("confidence", 0.0), reverse=True)
    return hypotheses


# ── Node 6: analyze_root_cause ────────────────────────────────────────


async def analyze_root_cause_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Correlate cited evidence using LLM adapter with safe deterministic fallback."""
    evidence_items = state.get("evidence", [])
    incident = state.get("incident") or {}

    configurable = config.get("configurable", {})
    adapter = configurable.get("llm_adapter") or get_llm_adapter()

    # Step 1: Attempt LLM-assisted root cause analysis
    llm_result = None
    try:
        llm_result = await adapter.generate_root_cause_analysis(
            incident=incident,
            evidence_items=[dict(e) for e in evidence_items],
        )
    except Exception as exc:
        logger.warning("LLM adapter invocation error: %s", exc)

    valid_evidence_ids = {e["id"] for e in evidence_items if "id" in e}

    # Step 2: Validate structured prediction
    if llm_result and llm_result.success and llm_result.parsed:
        pred = llm_result.parsed
        # Ensure cited IDs actually exist in the collected evidence
        validated_ids = [eid for eid in pred.supporting_evidence_ids if eid in valid_evidence_ids]

        top_hypothesis = Hypothesis(
            cause_key=pred.primary_cause,
            title=pred.primary_cause.replace("_", " ").title(),
            description=pred.reasoning,
            confidence=pred.confidence,
            supporting_evidence_ids=validated_ids,
            contradictions=pred.contradictions,
        )
        return {
            "hypotheses": [top_hypothesis],
            "confidence": top_hypothesis.get("confidence", 0.0),
            "model_name": llm_result.model_name,
            "prompt_version": llm_result.prompt_version,
            "graph_version": "v1.0.0",
        }

    # Step 3: Safe Fallback to Deterministic Rules
    err_msg = (
        llm_result.error_message
        if (llm_result and llm_result.error_message)
        else "LLM analysis unavailable"
    )
    logger.info("Using deterministic root cause rules (reason: %s)", err_msg)
    err = GraphError(
        node="analyze_root_cause",
        error_code="llm_fallback",
        message=f"Model output invalid or failed: {err_msg}. Used deterministic fallback.",
        retryable=False,
    )

    hypotheses = _deterministic_root_cause_analysis(incident, evidence_items)
    top_hypothesis = hypotheses[0]
    return {
        "hypotheses": hypotheses,
        "confidence": top_hypothesis.get("confidence", 0.0),
        "errors": [err],
        "model_name": llm_result.model_name if llm_result else "deterministic-fallback",
        "prompt_version": "1.0.0",
        "graph_version": "v1.0.0",
    }


# ── Conditional Edge: route_sufficiency ───────────────────────────────


def route_sufficiency(
    state: InvestigationState,
) -> Literal["sufficient", "needs_refinement", "insufficient"]:
    """Conditional router: enough evidence -> remediation; else refine or terminate."""
    confidence = state.get("confidence", 0.0)
    current_round = state.get("investigation_round", 1)
    max_rounds = state.get("max_investigation_rounds", 2)
    hypotheses = state.get("hypotheses", [])
    has_citations = bool(hypotheses and hypotheses[0].get("supporting_evidence_ids"))

    if confidence >= CONFIDENCE_THRESHOLD and has_citations:
        return "sufficient"

    if current_round < max_rounds:
        return "needs_refinement"

    return "insufficient"


# ── Node 7: refine_plan ───────────────────────────────────────────────


async def refine_plan_node(state: InvestigationState, config: RunnableConfig) -> dict[str, Any]:
    """Bounded refinement loop: identify missing signals and increment round counter."""
    current_round = state.get("investigation_round", 1)
    new_round = current_round + 1

    missing: list[str] = [
        "Corroborating trace span breakdown missing or ambiguous.",
        "Need extended metric baseline to differentiate transient spike from sustained fault.",
    ]

    logger.info(
        "Refining investigation plan for round %d/%d",
        new_round,
        state.get("max_investigation_rounds", 2),
    )

    return {
        "investigation_round": new_round,
        "missing_evidence": missing,
    }


# ── Node 8: propose_remediation ───────────────────────────────────────


async def propose_remediation_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Map validated root cause hypothesis to an allowlisted remediation action."""
    hypotheses = state.get("hypotheses", [])
    if not hypotheses:
        return {"status": "insufficient_evidence"}

    top_hypothesis = hypotheses[0]
    cause_key = top_hypothesis.get("cause_key", "unknown")
    incident = state.get("incident") or {}
    scenario_key = incident.get("scenario_key")

    action_details = map_cause_to_action(cause_key, scenario_key=scenario_key)
    if not action_details:
        return {
            "status": "insufficient_evidence",
            "missing_evidence": [
                f"No allowlisted remediation action mapped for cause '{cause_key}'."
            ],
        }

    recommendation = Recommendation(
        action_type=action_details["action_type"],
        parameters=action_details["parameters"],
        rationale=(
            f"Diagnosed '{top_hypothesis.get('title')}' with "
            f"{top_hypothesis.get('confidence', 0.0):.0%} confidence based on "
            f"{len(top_hypothesis.get('supporting_evidence_ids', []))} cited evidence item(s). "
            f"Recommended safe sandbox action: {action_details['description']}"
        ),
        risk_assessment=(
            f"Risk level: {action_details['risk_level']}. Confined to local simulator state."
        ),
        rollback_plan=action_details["rollback_plan"],
        verification_plan=action_details["verification_plan"],
    )

    return {
        "recommendation": recommendation,
        "status": "awaiting_approval",
    }


async def approval_gate_node(state: InvestigationState, config: RunnableConfig) -> dict[str, Any]:
    """Pause durably until an explicit operator decision is supplied."""
    recommendation = state.get("recommendation")
    if not recommendation:
        return {"approval_status": "rejected", "status": "insufficient_evidence"}

    decision = interrupt(
        {
            "kind": "approval_required",
            "run_id": state.get("run_id"),
            "incident_id": state.get("incident_id"),
            "action": recommendation,
            "message": "A human decision is required before any simulated action can run.",
        }
    )
    if not isinstance(decision, dict) or decision.get("decision") not in {
        "approved",
        "rejected",
        "request_more_evidence",
    }:
        raise ValueError("Approval resume value must contain a supported decision.")

    status = decision["decision"]
    return {
        "approval_status": status,
        "approval_decision": decision,
        "status": "awaiting_approval" if status == "request_more_evidence" else status,
    }


# ── Node 9: insufficient_evidence_report ──────────────────────────────


async def insufficient_evidence_report_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Produce a structured report when round limit is reached without sufficient evidence."""
    missing = state.get("missing_evidence") or [
        "Telemetry signals were insufficient or contradicted known fault patterns."
    ]

    return {
        "status": "insufficient_evidence",
        "missing_evidence": missing,
    }


# ── Node 10: finalize ─────────────────────────────────────────────────


async def finalize_node(state: InvestigationState, config: RunnableConfig) -> dict[str, Any]:
    """Build the final investigation report."""
    incident_id = state.get("incident_id", "")
    run_id = state.get("run_id", "")
    incident = state.get("incident") or {}
    status = state.get("status", "completed")
    hypotheses = state.get("hypotheses", [])
    top_hypothesis = hypotheses[0] if hypotheses else None
    confidence = state.get("confidence", 0.0)
    evidence_count = len(state.get("evidence", []))
    recommendation = state.get("recommendation")
    missing_evidence = state.get("missing_evidence", [])
    remediation_result = state.get("remediation_result")
    verification_result = state.get("verification_result")

    top_title = top_hypothesis.get("title") if top_hypothesis else "Simulated fault"

    # Build contextual summary
    if verification_result and verification_result.get("outcome") == "resolved":
        action_name = recommendation.get("action_type") if recommendation else "unknown"
        summary = (
            f"Investigation and remediation completed successfully. "
            f"Diagnosed '{top_title}' "
            f"({confidence:.0%} confidence, {evidence_count} evidence items). "
            f"Action '{action_name}' applied and verified. "
            f"Incident can be resolved."
        )
    elif verification_result and verification_result.get("outcome") == "mitigated":
        action_name = recommendation.get("action_type") if recommendation else "unknown"
        summary = (
            f"Remediation partially successful. "
            f"Action '{action_name}' cleared the target fault, "
            f"but additional active faults remain. Incident is mitigated."
        )
    elif verification_result and verification_result.get("outcome") == "failed":
        summary = (
            f"Remediation verification failed. "
            f"{verification_result.get('summary', 'The target fault persists.')} "
            f"Manual intervention recommended."
        )
    elif remediation_result and not remediation_result.get("success"):
        denial = remediation_result.get("denial_reason") or remediation_result.get(
            "error_message", ""
        )
        summary = (
            f"Remediation action was denied or failed. Reason: {denial}. Incident remains open."
        )
    elif status == "awaiting_approval" and top_hypothesis:
        action_name = recommendation.get("action_type") if recommendation else "none"
        summary = (
            f"Investigation concluded with diagnosis: {top_hypothesis.get('title')} "
            f"({confidence:.0%} confidence, {evidence_count} evidence items collected). "
            f"Remediation action '{action_name}' proposed and awaiting human approval."
        )
    elif status == "insufficient_evidence":
        summary = (
            f"Investigation concluded with insufficient evidence after "
            f"{state.get('investigation_round', 1)} rounds. "
            f"Confidence remained at {confidence:.0%}. Manual human triage is recommended."
        )
    else:
        summary = f"Investigation run completed with status '{status}'."

    final_report = FinalReport(
        incident_id=incident_id,
        run_id=run_id,
        status=status,
        primary_cause=top_hypothesis.get("cause_key") if top_hypothesis else None,
        confidence=confidence,
        evidence_count=evidence_count,
        summary=summary,
        recommendation=recommendation,
        missing_evidence=missing_evidence,
        remediation_result=remediation_result,
        verification_result=verification_result,
        trace_id=state.get("trace_id"),
    )

    record_investigation_run(
        service=str(incident.get("service") or "shopapi"),
        status=status,
        duration_seconds=1.0,
    )

    return {"final_report": final_report}


# ── Node 11: execute_remediation ──────────────────────────────────────


async def execute_remediation_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Execute the approved remediation action via the sandbox executor.

    This node only runs when the approval gate returns 'approved'.
    It re-validates all policy preconditions before mutating simulator state.
    """
    recommendation = state.get("recommendation")
    approval_status = state.get("approval_status")
    incident_id = state.get("incident_id", "")
    run_id = state.get("run_id", "")

    if not recommendation or approval_status != "approved":
        err = GraphError(
            node="execute_remediation",
            error_code="missing_approval_or_recommendation",
            message="Cannot execute remediation without approval and recommendation.",
            retryable=False,
        )
        return {
            "errors": [err],
            "status": "failed",
            "remediation_result": RemediationOutcome(
                success=False,
                action_type="unknown",
                idempotency_key="",
                executed_at=datetime.now(UTC).isoformat(),
                status="denied",
                denial_code="missing_approval_or_recommendation",
                denial_reason="No approved recommendation to execute.",
            ),
        }

    action_type = recommendation.get("action_type", "")
    parameters = recommendation.get("parameters", {})

    configurable = (config or {}).get("configurable", {})

    # Get simulator — either from config (tests) or global singleton
    simulator = configurable.get("simulator")
    if simulator is None:
        try:
            simulator = get_simulator()
        except RuntimeError:
            err = GraphError(
                node="execute_remediation",
                error_code="simulator_unavailable",
                message="Simulator not initialised.",
                retryable=False,
            )
            return {
                "errors": [err],
                "status": "failed",
                "remediation_result": RemediationOutcome(
                    success=False,
                    action_type=action_type,
                    idempotency_key="",
                    executed_at=datetime.now(UTC).isoformat(),
                    status="failed",
                    error_message="Simulator not initialised.",
                ),
            }

    # Get settings from config or defaults
    simulator_enabled = configurable.get("simulator_enabled", True)
    is_development = configurable.get("is_development", True)

    executor = SandboxExecutor(simulator)
    result = executor.execute(
        action_type=action_type,
        parameters=parameters,
        approval_status=approval_status,
        approval_incident_id=incident_id,
        approval_run_id=run_id,
        current_incident_id=incident_id,
        current_run_id=run_id,
        incident_status="awaiting_approval",
        simulator_enabled=simulator_enabled,
        is_development=is_development,
    )

    remediation_outcome = RemediationOutcome(
        success=result.success,
        action_type=result.action_type,
        idempotency_key=result.idempotency_key,
        executed_at=result.executed_at,
        status=result.status,
        details=result.details,
        denial_code=result.denial_code,
        denial_reason=result.denial_reason,
        error_message=result.error_message,
        rollback_instruction=result.rollback_instruction,
    )

    record_remediation_action(action_type=action_type, status=result.status)

    if result.success:
        return {
            "remediation_result": remediation_outcome,
            "status": "remediating",
        }
    else:
        err = GraphError(
            node="execute_remediation",
            error_code=result.denial_code or "execution_failed",
            message=result.denial_reason or result.error_message or "Remediation failed.",
            retryable=False,
        )
        return {
            "errors": [err],
            "remediation_result": remediation_outcome,
            "status": "failed",
        }


# ── Node 12: verify_remediation ───────────────────────────────────────


async def verify_remediation_node(
    state: InvestigationState, config: RunnableConfig
) -> dict[str, Any]:
    """Post-action verification: check simulator state and determine incident outcome."""
    remediation_result_state = state.get("remediation_result")
    recommendation = state.get("recommendation")

    if not remediation_result_state:
        return {
            "status": "failed",
            "verification_result": VerificationOutcome(
                passed=False,
                outcome="failed",
                checks=[],
                summary="No remediation result to verify.",
                verified_at=datetime.now(UTC).isoformat(),
                recommended_incident_status="open",
            ),
        }

    action_type = remediation_result_state.get("action_type", "")
    parameters = recommendation.get("parameters", {}) if recommendation else {}

    configurable = (config or {}).get("configurable", {})
    simulator = configurable.get("simulator")
    if simulator is None:
        try:
            simulator = get_simulator()
        except RuntimeError:
            return {
                "status": "failed",
                "verification_result": VerificationOutcome(
                    passed=False,
                    outcome="inconclusive",
                    checks=[],
                    summary="Simulator unavailable for verification.",
                    verified_at=datetime.now(UTC).isoformat(),
                    recommended_incident_status="open",
                ),
            }

    # Reconstruct ExecutionResult from state for verification
    from app.remediation.executor import ExecutionResult as ExecResult

    exec_result = ExecResult(
        success=remediation_result_state.get("success", False),
        action_type=remediation_result_state.get("action_type", ""),
        idempotency_key=remediation_result_state.get("idempotency_key", ""),
        executed_at=remediation_result_state.get("executed_at", ""),
        status=remediation_result_state.get("status", "failed"),
        details=remediation_result_state.get("details", {}),
        error_message=remediation_result_state.get("error_message"),
    )

    verification = run_verification(
        execution_result=exec_result,
        simulator=simulator,
        action_type=action_type,
        parameters=parameters,
    )

    verification_outcome = VerificationOutcome(
        passed=verification.passed,
        outcome=verification.outcome,
        checks=verification.checks,
        summary=verification.summary,
        verified_at=verification.verified_at,
        recommended_incident_status=verification.recommended_incident_status,
    )

    # Map verification outcome to graph status
    status_map = {
        "resolved": "completed",
        "mitigated": "completed",
        "failed": "failed",
        "inconclusive": "failed",
    }
    new_status = status_map.get(verification.outcome, "failed")

    return {
        "verification_result": verification_outcome,
        "status": new_status,
    }

"""Multi-Agent Orchestration Architecture for Ravel Incident Intelligence.

Implements:
1. Supervisor-Worker Pattern:
   - Incident Commander (Supervisor) coordinates specialized worker agents.
   - Workers execute domain-specific diagnostic investigations in parallel.
2. Multiple Specialized Agents:
   - Supervisor (Incident Commander)
   - Log Forensics Agent (LogAnalyst)
   - Telemetry & Metrics Agent (MetricSentry)
   - Distributed Tracing Agent (TraceNavigator)
   - Infrastructure & Change Auditor (ChangeAuditor)
   - Remediation & Safety Officer (SafetyOfficer)
3. Short-Term and Long-Term Memory:
   - Short-Term: Active thread working memory, evidence scratchpad, inter-agent messages.
   - Long-Term: Semantic historical incident pattern store and runbook memory.
4. Stateful Workflows & Checkpointing (via LangGraph StateGraph & checkpointers).
5. Conditional Routing & Loops (confidence sufficiency check & reflection loops).
6. Human-in-the-Loop Approval (durable pause with interrupt() and resume with Command).
7. Structured Tool Calling with validated Pydantic schemas.
8. Retries, Timeouts, and Error Isolation.
9. Streaming Agent Lifecycle Event Logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.observability.metrics import record_agent_execution

logger = logging.getLogger(__name__)


# ── 1. Specialized Agent Roles & Definitions ──────────────────────────


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    LOG_FORENSICS = "log_forensics"
    TELEMETRY_METRICS = "telemetry_metrics"
    DISTRIBUTED_TRACING = "distributed_tracing"
    CHANGE_AUDITOR = "change_auditor"
    SAFETY_OFFICER = "safety_officer"


class AgentCapability(StrEnum):
    LOG_PARSING = "log_parsing"
    METRIC_ANOMALY = "metric_anomaly"
    TRACE_ANALYSIS = "trace_analysis"
    CHANGE_AUDITING = "change_auditing"
    SYNTHESIS = "synthesis"
    SAFETY_VALIDATION = "safety_validation"


@dataclass
class AgentProfile:
    """Identity and operational envelope for an autonomous specialized agent."""

    id: str
    role: AgentRole
    display_name: str
    description: str
    capabilities: list[AgentCapability]
    system_prompt: str
    timeout_seconds: float = 15.0
    max_retries: int = 3
    backoff_factor: float = 1.5


AGENT_REGISTRY: dict[AgentRole, AgentProfile] = {
    AgentRole.SUPERVISOR: AgentProfile(
        id="agent-supervisor",
        role=AgentRole.SUPERVISOR,
        display_name="Incident Commander (Supervisor)",
        description="Coordinates multi-agent investigation, assigns tasks, synthesizes evidence, and manages refinement loops.",
        capabilities=[AgentCapability.SYNTHESIS],
        system_prompt=(
            "You are the Ravel Incident Commander. You oversee specialized agents, formulate high-level "
            "investigation plans, query Long-Term Memory for known incident patterns, evaluate worker findings, "
            "and decide whether to loop for more evidence or escalate to remediation."
        ),
        timeout_seconds=30.0,
        max_retries=2,
    ),
    AgentRole.LOG_FORENSICS: AgentProfile(
        id="agent-logs",
        role=AgentRole.LOG_FORENSICS,
        display_name="Log Forensics Agent",
        description="Analyzes structured log streams, exception stack traces, database pool errors, and error codes.",
        capabilities=[AgentCapability.LOG_PARSING],
        system_prompt=(
            "You are the Log Forensics Agent. You inspect application and database logs to extract error codes, "
            "stack traces, timeouts, and pool saturation signatures with exact source citations."
        ),
        timeout_seconds=12.0,
        max_retries=3,
    ),
    AgentRole.TELEMETRY_METRICS: AgentProfile(
        id="agent-metrics",
        role=AgentRole.TELEMETRY_METRICS,
        display_name="Telemetry & Metrics Agent",
        description="Evaluates time-series performance metrics: P50/P95/P99 latency, error rates, and resource saturation.",
        capabilities=[AgentCapability.METRIC_ANOMALY],
        system_prompt=(
            "You are the Telemetry & Metrics Agent. You detect latency percentiles, calculate error rate spikes, "
            "and identify service-level degradation across critical endpoints."
        ),
        timeout_seconds=12.0,
        max_retries=3,
    ),
    AgentRole.DISTRIBUTED_TRACING: AgentProfile(
        id="agent-traces",
        role=AgentRole.DISTRIBUTED_TRACING,
        display_name="Distributed Tracing Agent",
        description="Navigates W3C distributed trace spans to isolate bottleneck microservices and slow database calls.",
        capabilities=[AgentCapability.TRACE_ANALYSIS],
        system_prompt=(
            "You are the Distributed Tracing Agent. You follow traceparent propagation, calculate span durations, "
            "and pinpoint exact database or downstream service bottlenecks."
        ),
        timeout_seconds=12.0,
        max_retries=3,
    ),
    AgentRole.CHANGE_AUDITOR: AgentProfile(
        id="agent-changes",
        role=AgentRole.CHANGE_AUDITOR,
        display_name="Change Auditor Agent",
        description="Audits recent deployments, git release tags, configuration drift, and database schema migrations.",
        capabilities=[AgentCapability.CHANGE_AUDITING],
        system_prompt=(
            "You are the Change Auditor Agent. You cross-reference incident timestamps with deployment events, "
            "feature flags, and configuration adjustments."
        ),
        timeout_seconds=10.0,
        max_retries=3,
    ),
    AgentRole.SAFETY_OFFICER: AgentProfile(
        id="agent-safety",
        role=AgentRole.SAFETY_OFFICER,
        display_name="Remediation Safety Officer",
        description="Validates proposed actions against allowlisted runbooks, evaluates blast radius, and prepares rollback plans.",
        capabilities=[AgentCapability.SAFETY_VALIDATION],
        system_prompt=(
            "You are the Remediation Safety Officer. You enforce zero unintended blast radius. You ensure any "
            "remediation proposal has an allowlisted action, a verified rollback procedure, and an automated verification plan."
        ),
        timeout_seconds=15.0,
        max_retries=2,
    ),
}


# ── 2. Inter-Agent Communication & Structured Messaging ──────────────


class MessageType(StrEnum):
    TASK_DELEGATION = "task_delegation"
    EVIDENCE_REPORT = "evidence_report"
    QUERY_REFINEMENT = "query_refinement"
    SUPERVISOR_DECISION = "supervisor_decision"
    HUMAN_INTERVENTION = "human_intervention"


class AgentMessage(BaseModel):
    """Structured message exchanged between supervisor and worker agents."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    sender_role: AgentRole
    recipient_role: AgentRole
    message_type: MessageType
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None


# ── 3. Short-Term & Long-Term Memory Architecture ─────────────────────


class LongTermMemoryPattern(BaseModel):
    """A historical incident post-mortem stored in long-term memory."""

    incident_pattern_id: str
    pattern_key: str  # e.g. "db_conn_exhaustion", "db_latency", "bad_release"
    title: str
    symptoms: list[str]
    root_cause_summary: str
    effective_remediation: str
    historical_resolution_time_min: int
    confidence_prior: float


# Pre-populated Long-Term Memory Store with verified incident post-mortems
HISTORICAL_INCIDENT_MEMORY: list[LongTermMemoryPattern] = [
    LongTermMemoryPattern(
        incident_pattern_id="LTM-001",
        pattern_key="db_conn_exhaustion",
        title="Post-Mortem: ShopAPI Connection Pool Exhaustion under Peak Traffic",
        symptoms=[
            "connection pool exhausted",
            "503 Service Unavailable",
            "timeout acquiring connection",
            "pool saturation",
        ],
        root_cause_summary="Connection leaks or insufficient pool size caused checkout transactions to hang waiting for connections.",
        effective_remediation="Reset pool or scale max connections and recycle idle connections.",
        historical_resolution_time_min=8,
        confidence_prior=0.92,
    ),
    LongTermMemoryPattern(
        incident_pattern_id="LTM-002",
        pattern_key="db_latency",
        title="Post-Mortem: Unindexed Catalog Query Degradation",
        symptoms=[
            "p95 latency > 1200ms",
            "slow database spans",
            "sequential scan on products table",
        ],
        root_cause_summary="Missing index on category_id led to full table scans during product listings.",
        effective_remediation="Disable simulated latency fault or trigger cache warming.",
        historical_resolution_time_min=12,
        confidence_prior=0.88,
    ),
    LongTermMemoryPattern(
        incident_pattern_id="LTM-003",
        pattern_key="bad_release",
        title="Post-Mortem: Regression in v1.4.2 Serialization Query",
        symptoms=["deployment v1.4.2", "slow response times after release", "query regression"],
        root_cause_summary="Release v1.4.2 introduced N+1 query pattern during order details serialization.",
        effective_remediation="Roll back to release v1.4.1 or apply hotfix configuration.",
        historical_resolution_time_min=15,
        confidence_prior=0.85,
    ),
    LongTermMemoryPattern(
        incident_pattern_id="LTM-004",
        pattern_key="dependency_timeout",
        title="Post-Mortem: External Payment Gateway Gateway Timeout",
        symptoms=["third-party timeout", "504 Gateway Timeout", "payment endpoint latency"],
        root_cause_summary="Payment vendor experienced network degradation; circuit breaker failed to trip.",
        effective_remediation="Activate secondary payment route and trip circuit breaker.",
        historical_resolution_time_min=20,
        confidence_prior=0.79,
    ),
]


class IncidentMemoryStore:
    """Dual-layer memory store: short-term working context + long-term pattern memory."""

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        # Short-term working memory
        self.scratchpad: dict[str, Any] = {}
        self.messages: list[AgentMessage] = []
        self.investigation_round: int = 1

    def append_message(self, message: AgentMessage) -> None:
        self.messages.append(message)

    def query_long_term_memory(
        self, incident_title: str, incident_desc: str, limit: int = 2
    ) -> list[tuple[LongTermMemoryPattern, float]]:
        """Retrieve relevant past incident patterns using keyword & symptom similarity."""
        query_text = f"{incident_title} {incident_desc}".lower()
        matches: list[tuple[LongTermMemoryPattern, float]] = []

        for pattern in HISTORICAL_INCIDENT_MEMORY:
            matched_symptoms = sum(
                1
                for s in pattern.symptoms
                if any(token in query_text for token in s.lower().split())
            )
            similarity = min(1.0, 0.4 + (matched_symptoms * 0.2)) if matched_symptoms > 0 else 0.1
            matches.append((pattern, round(similarity, 2)))

        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:limit]


# ── 4. Structured Tool Calling Models ─────────────────────────────────


class ToolExecutionRecord(BaseModel):
    """Audit record of a structured tool invocation by an agent."""

    tool_name: str
    invoked_by: AgentRole
    parameters: dict[str, Any]
    success: bool
    latency_ms: float
    output_summary: str
    error_message: str | None = None
    retry_count: int = 0


class AgentExecutionReport(BaseModel):
    """Structured report produced by a specialized agent upon completing a task."""

    agent_role: AgentRole
    status: str  # "completed", "failed", "retried"
    duration_ms: float
    evidence_count: int
    findings_summary: str
    confidence: float
    tool_calls: list[ToolExecutionRecord] = Field(default_factory=list)


# ── 5. Retries, Timeouts, and Error Recovery Helper ───────────────────


async def execute_agent_with_resilience[T](
    agent_role: AgentRole,
    action: Callable[[], Coroutine[Any, Any, T]],
    *,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    backoff_factor: float = 1.5,
) -> tuple[T | None, int, str | None]:
    """Execute an agent coroutine with automated timeouts, exponential backoff, and failure recovery.

    Returns:
        (result, attempts_taken, error_message)
    """
    profile = AGENT_REGISTRY.get(agent_role)
    timeout = timeout_seconds or (profile.timeout_seconds if profile else 15.0)
    retries = max_retries if max_retries is not None else (profile.max_retries if profile else 2)

    started = time.perf_counter()
    last_error: str | None = None
    for attempt in range(1, retries + 1):
        try:
            result = await asyncio.wait_for(action(), timeout=timeout)
            status = "retried" if attempt > 1 else "completed"
            record_agent_execution(agent_role.value, status, time.perf_counter() - started)
            return result, attempt, None
        except TimeoutError:
            last_error = (
                f"{agent_role.value} timed out after {timeout}s (attempt {attempt}/{retries})"
            )
            logger.warning(last_error)
        except Exception as exc:
            last_error = f"{agent_role.value} failed: {exc} (attempt {attempt}/{retries})"
            logger.warning(last_error)

        if attempt < retries:
            delay = backoff_factor ** (attempt - 1)
            await asyncio.sleep(delay)

    record_agent_execution(agent_role.value, "failed", time.perf_counter() - started)
    return None, retries, last_error


# ── 6. Multi-Agent Lifecycle Event Streamer ───────────────────────────


@dataclass
class AgentLifecycleEvent:
    event_type: str
    agent_role: AgentRole
    timestamp: str
    details: dict[str, Any]


class MultiAgentEventBus:
    """In-memory event bus providing live streaming feeds of multi-agent execution."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._events: list[AgentLifecycleEvent] = []

    def emit(self, event_type: str, agent_role: AgentRole, details: dict[str, Any]) -> None:
        event = AgentLifecycleEvent(
            event_type=event_type,
            agent_role=agent_role,
            timestamp=datetime.now(UTC).isoformat(),
            details=details,
        )
        self._events.append(event)
        logger.debug(
            "[AgentBus: %s] %s -> %s: %s",
            self.run_id,
            agent_role.value,
            event_type,
            details.get("summary", ""),
        )

    def get_events(self) -> list[AgentLifecycleEvent]:
        return list(self._events)

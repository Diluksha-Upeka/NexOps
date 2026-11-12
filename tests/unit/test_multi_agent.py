"""Unit tests for Ravel multi-agent profiles, dual memory, tool schemas, and resilience."""

from __future__ import annotations

import asyncio

import pytest

from app.graph.agents import (
    AGENT_REGISTRY,
    HISTORICAL_INCIDENT_MEMORY,
    AgentCapability,
    AgentExecutionReport,
    AgentMessage,
    AgentRole,
    IncidentMemoryStore,
    MessageType,
    MultiAgentEventBus,
    ToolExecutionRecord,
    execute_agent_with_resilience,
)


def test_agent_registry_defines_all_specialized_roles() -> None:
    """Every AgentRole enum member should be registered with valid policy constraints."""
    for role in AgentRole:
        assert role in AGENT_REGISTRY
        profile = AGENT_REGISTRY[role]
        assert profile.role == role
        assert profile.timeout_seconds > 0
        assert profile.max_retries >= 1
        assert len(profile.capabilities) >= 1
        assert profile.system_prompt

    assert AgentCapability.SYNTHESIS in AGENT_REGISTRY[AgentRole.SUPERVISOR].capabilities
    assert (
        AgentCapability.SAFETY_VALIDATION in AGENT_REGISTRY[AgentRole.SAFETY_OFFICER].capabilities
    )


def test_incident_memory_store_short_and_long_term() -> None:
    """Memory store maintains thread scratchpad and ranks matching post-mortem patterns."""
    store = IncidentMemoryStore(thread_id="thread-test-001")
    msg = AgentMessage(
        sender_role=AgentRole.SUPERVISOR,
        recipient_role=AgentRole.LOG_FORENSICS,
        message_type=MessageType.TASK_DELEGATION,
        summary="Check pool exhaustion logs",
    )
    store.append_message(msg)
    assert len(store.messages) == 1
    assert store.messages[0].recipient_role == AgentRole.LOG_FORENSICS

    matches = store.query_long_term_memory(
        incident_title="ShopAPI 503 Service Unavailable connection pool exhausted",
        incident_desc="Checkout calls timing out due to pool saturation",
        limit=2,
    )
    assert len(matches) == 2
    top_pattern, top_similarity = matches[0]
    assert top_pattern.pattern_key == "db_conn_exhaustion"
    assert top_similarity >= 0.6
    assert HISTORICAL_INCIDENT_MEMORY


def test_structured_tool_and_execution_report_models() -> None:
    """Pydantic tool invocation and agent execution report serialize cleanly."""
    tool_rec = ToolExecutionRecord(
        tool_name="query_logs",
        invoked_by=AgentRole.LOG_FORENSICS,
        parameters={"service": "shopapi", "limit": 50},
        success=True,
        latency_ms=14.2,
        output_summary="Found 12 connection timeout errors.",
    )
    report = AgentExecutionReport(
        agent_role=AgentRole.LOG_FORENSICS,
        status="completed",
        duration_ms=18.5,
        evidence_count=3,
        findings_summary="Repeated connection pool wait timeouts.",
        confidence=0.88,
        tool_calls=[tool_rec],
    )
    dumped = report.model_dump(mode="json")
    assert dumped["agent_role"] == "log_forensics"
    assert dumped["tool_calls"][0]["tool_name"] == "query_logs"


@pytest.mark.asyncio
async def test_execute_agent_with_resilience_retries_and_recovers() -> None:
    """Transient worker failure retries with backoff and succeeds before max attempts."""
    attempts = 0

    async def flaky_worker() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise RuntimeError("Transient telemetry store glitch")
        return "metrics-ok"

    result, taken, err = await execute_agent_with_resilience(
        AgentRole.TELEMETRY_METRICS,
        flaky_worker,
        timeout_seconds=2.0,
        max_retries=3,
        backoff_factor=1.01,
    )
    assert result == "metrics-ok"
    assert taken == 2
    assert err is None


@pytest.mark.asyncio
async def test_execute_agent_with_resilience_timeout_isolation() -> None:
    """Agent exceeding its deadline exhausts bounded retries and returns structured error."""

    async def stalling_worker() -> str:
        await asyncio.sleep(0.3)
        return "unreachable"

    result, taken, err = await execute_agent_with_resilience(
        AgentRole.CHANGE_AUDITOR,
        stalling_worker,
        timeout_seconds=0.04,
        max_retries=2,
        backoff_factor=1.01,
    )
    assert result is None
    assert taken == 2
    assert err is not None
    assert "timed out" in err


def test_multi_agent_event_bus_records_lifecycle() -> None:
    """Lifecycle bus captures ordered immutable snapshots of emitted agent events."""
    bus = MultiAgentEventBus(run_id="run-123")
    bus.emit("task_started", AgentRole.LOG_FORENSICS, {"summary": "Scanning logs"})
    bus.emit("task_finished", AgentRole.LOG_FORENSICS, {"summary": "3 errors isolated"})
    events = bus.get_events()
    assert len(events) == 2
    assert events[0].event_type == "task_started"
    assert events[1].agent_role == AgentRole.LOG_FORENSICS

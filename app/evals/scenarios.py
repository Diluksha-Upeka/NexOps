"""Canonical evaluation scenarios with ground-truth expectations for Phase 4.

Each scenario defines:
  - Incident context
  - Expected root cause
  - Must-find evidence types (for recall measurement)
  - Forbidden claims (to detect hallucinations / false positives)
  - Expected allowlisted remediation action
  - Expected terminal status
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvaluationScenario:
    """A benchmark test scenario with ground-truth labels."""

    key: str
    title: str
    description: str
    service: str
    severity: str
    scenario_key: str | None
    expected_cause: str
    must_find_evidence: list[str]
    forbidden_claims: list[str]
    expected_action: str | None
    expected_status: str  # "awaiting_approval" | "insufficient_evidence"
    synthetic_evidence: list[dict[str, Any]] = field(default_factory=list)


# ── Scenario Suite (v1.0.0) ───────────────────────────────────────────

EVAL_SCENARIOS: list[EvaluationScenario] = [
    EvaluationScenario(
        key="db_latency",
        title="High latency on ShopAPI product queries",
        description="P95 latency rose from 320ms to 1420ms; DB queries stalled.",
        service="shopapi",
        severity="high",
        scenario_key="db_latency",
        expected_cause="db_latency",
        must_find_evidence=["metrics", "traces"],
        forbidden_claims=["bad_release", "dependency_timeout"],
        expected_action="disable_fault",
        expected_status="awaiting_approval",
        synthetic_evidence=[
            {
                "id": "ev-metrics-1",
                "source_type": "metrics",
                "source_ref": "metrics:shopapi:request_duration:w1",
                "summary": (
                    "Sampled 120 request durations. p95=1420ms, avg=890ms. "
                    "Significant latency degradation observed."
                ),
                "data": {"p95_ms": 1420.0, "avg_ms": 890.0, "latency_degraded": True},
                "confidence": 0.90,
            },
            {
                "id": "ev-traces-1",
                "source_type": "traces",
                "source_ref": "traces:shopapi:w1",
                "summary": (
                    "Queried 45 trace spans for shopapi. Identified 8 slow database spans (>400ms)."
                ),
                "data": {"span_count": 45, "slow_db_span_count": 8, "has_slow_db": True},
                "confidence": 0.88,
            },
            {
                "id": "ev-logs-1",
                "source_type": "logs",
                "source_ref": "logs:shopapi:w1",
                "summary": "Queried 50 logs for shopapi. Found 0 error-level logs.",
                "data": {"total_logs": 50, "error_count": 0, "pool_error_count": 0},
                "confidence": 0.85,
            },
            {
                "id": "ev-changes-1",
                "source_type": "changes",
                "source_ref": "changes:shopapi:w1",
                "summary": (
                    "Queried change history. Found 0 total changes in the observation window."
                ),
                "data": {"total_changes": 0, "deployment_count": 0},
                "confidence": 0.90,
            },
        ],
    ),
    EvaluationScenario(
        key="db_connection_exhaustion",
        title="Database connection pool exhausted",
        description="Pool saturated; requests returning 503 and connection timeouts.",
        service="shopapi",
        severity="critical",
        scenario_key="db_connection_exhaustion",
        expected_cause="db_connection_exhaustion",
        must_find_evidence=["logs"],
        forbidden_claims=["bad_release", "dependency_timeout"],
        expected_action="disable_fault",
        expected_status="awaiting_approval",
        synthetic_evidence=[
            {
                "id": "ev-logs-2",
                "source_type": "logs",
                "source_ref": "logs:shopapi:w2",
                "summary": (
                    "Queried 40 logs for shopapi. Found 12 error-level logs. "
                    "Detected 12 connection pool exhaustion errors."
                ),
                "data": {"total_logs": 40, "error_count": 12, "pool_error_count": 12},
                "confidence": 0.90,
            },
            {
                "id": "ev-metrics-2",
                "source_type": "metrics",
                "source_ref": "metrics:shopapi:w2",
                "summary": "Sampled 80 request durations. p95=340ms, avg=290ms.",
                "data": {"p95_ms": 340.0, "avg_ms": 290.0, "latency_degraded": False},
                "confidence": 0.85,
            },
            {
                "id": "ev-changes-2",
                "source_type": "changes",
                "source_ref": "changes:shopapi:w2",
                "summary": (
                    "Queried change history. Found 0 total changes in the observation window."
                ),
                "data": {"total_changes": 0, "deployment_count": 0},
                "confidence": 0.90,
            },
        ],
    ),
    EvaluationScenario(
        key="bad_release",
        title="Slow product queries following release v1.2.0",
        description="Configuration revision deployed 15m ago caused query slowdown.",
        service="shopapi",
        severity="high",
        scenario_key="bad_release",
        expected_cause="bad_release",
        must_find_evidence=["changes", "metrics"],
        forbidden_claims=["dependency_timeout"],
        expected_action="rollback_release",
        expected_status="awaiting_approval",
        synthetic_evidence=[
            {
                "id": "ev-changes-3",
                "source_type": "changes",
                "source_ref": "changes:shopapi:w3",
                "summary": "Queried change history. Detected 1 recent deployment/release changes.",
                "data": {
                    "total_changes": 1,
                    "deployment_count": 1,
                    "recent_deployments": [{"revision": "v1.2.0", "type": "deployment"}],
                },
                "confidence": 0.92,
            },
            {
                "id": "ev-metrics-3",
                "source_type": "metrics",
                "source_ref": "metrics:shopapi:w3",
                "summary": (
                    "Sampled 95 request durations. p95=1100ms, avg=720ms. "
                    "Significant latency degradation observed."
                ),
                "data": {"p95_ms": 1100.0, "avg_ms": 720.0, "latency_degraded": True},
                "confidence": 0.89,
            },
            {
                "id": "ev-logs-3",
                "source_type": "logs",
                "source_ref": "logs:shopapi:w3",
                "summary": "Queried 30 logs for shopapi. Found 0 error-level logs.",
                "data": {"total_logs": 30, "error_count": 0, "pool_error_count": 0},
                "confidence": 0.85,
            },
        ],
    ),
    EvaluationScenario(
        key="dependency_timeout",
        title="Payment gateway timeout during checkout",
        description="External partner service latency exceeding 5s timeout.",
        service="shopapi",
        severity="high",
        scenario_key="dependency_timeout",
        expected_cause="dependency_timeout",
        must_find_evidence=["traces"],
        forbidden_claims=["db_connection_exhaustion"],
        expected_action="disable_fault",
        expected_status="awaiting_approval",
        synthetic_evidence=[
            {
                "id": "ev-traces-4",
                "source_type": "traces",
                "source_ref": "traces:shopapi:w4",
                "summary": (
                    "Queried 35 trace spans for shopapi. Identified 6 dependency timeout spans."
                ),
                "data": {"span_count": 35, "timeout_span_count": 6, "has_timeout": True},
                "confidence": 0.89,
            },
            {
                "id": "ev-logs-4",
                "source_type": "logs",
                "source_ref": "logs:shopapi:w4",
                "summary": "Queried 50 logs for shopapi. Found 6 error-level logs.",
                "data": {"total_logs": 50, "error_count": 6, "pool_error_count": 0},
                "confidence": 0.85,
            },
            {
                "id": "ev-changes-4",
                "source_type": "changes",
                "source_ref": "changes:shopapi:w4",
                "summary": (
                    "Queried change history. Found 0 total changes in the observation window."
                ),
                "data": {"total_changes": 0, "deployment_count": 0},
                "confidence": 0.90,
            },
        ],
    ),
    EvaluationScenario(
        key="elevated_5xx",
        title="Elevated 500 error rates on ShopAPI",
        description="Application server returning internal errors on cart checkout.",
        service="shopapi",
        severity="high",
        scenario_key="elevated_5xx",
        expected_cause="elevated_5xx",
        must_find_evidence=["logs"],
        forbidden_claims=["bad_release", "dependency_timeout"],
        expected_action="disable_fault",
        expected_status="awaiting_approval",
        synthetic_evidence=[
            {
                "id": "ev-logs-5",
                "source_type": "logs",
                "source_ref": "logs:shopapi:w5",
                "summary": "Queried 60 logs for shopapi. Found 15 error-level logs.",
                "data": {"total_logs": 60, "error_count": 15, "pool_error_count": 0},
                "confidence": 0.88,
            },
            {
                "id": "ev-metrics-5",
                "source_type": "metrics",
                "source_ref": "metrics:shopapi:w5",
                "summary": "Sampled 70 request durations. p95=310ms, avg=250ms.",
                "data": {"p95_ms": 310.0, "avg_ms": 250.0, "latency_degraded": False},
                "confidence": 0.85,
            },
            {
                "id": "ev-changes-5",
                "source_type": "changes",
                "source_ref": "changes:shopapi:w5",
                "summary": (
                    "Queried change history. Found 0 total changes in the observation window."
                ),
                "data": {"total_changes": 0, "deployment_count": 0},
                "confidence": 0.90,
            },
        ],
    ),
    EvaluationScenario(
        key="ambiguous_jitter",
        title="Minor network jitter on ShopAPI",
        description="Routine minor telemetry jitter without clear degradation pattern.",
        service="shopapi",
        severity="low",
        scenario_key=None,
        expected_cause="unknown",
        must_find_evidence=[],
        forbidden_claims=["db_latency", "bad_release", "db_connection_exhaustion"],
        expected_action=None,
        expected_status="insufficient_evidence",
        synthetic_evidence=[
            {
                "id": "ev-metrics-6",
                "source_type": "metrics",
                "source_ref": "metrics:shopapi:w6",
                "summary": "Sampled 40 request durations. p95=315ms, avg=260ms.",
                "data": {"p95_ms": 315.0, "avg_ms": 260.0, "latency_degraded": False},
                "confidence": 0.85,
            },
            {
                "id": "ev-logs-6",
                "source_type": "logs",
                "source_ref": "logs:shopapi:w6",
                "summary": "Queried 30 logs for shopapi. Found 0 error-level logs.",
                "data": {"total_logs": 30, "error_count": 0, "pool_error_count": 0},
                "confidence": 0.85,
            },
            {
                "id": "ev-changes-6",
                "source_type": "changes",
                "source_ref": "changes:shopapi:w6",
                "summary": (
                    "Queried change history. Found 0 total changes in the observation window."
                ),
                "data": {"total_changes": 0, "deployment_count": 0},
                "confidence": 0.90,
            },
        ],
    ),
]

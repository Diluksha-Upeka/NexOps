"""Fault injection scenario definitions and simulator state management.

Each scenario has a stable key, description, expected root cause, allowed
safe fix, severity, TTL, and cleanup behaviour.  The simulator is entirely
in-memory — no database table needed for Phase 1 — and every fault has
automatic TTL expiry and a hard safety cap from settings.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.settings import Settings

logger = logging.getLogger(__name__)


class ScenarioKey(StrEnum):
    """Stable keys for built-in fault scenarios."""

    DB_LATENCY = "db_latency"
    DB_CONN_EXHAUSTION = "db_conn_exhaustion"
    DEPENDENCY_TIMEOUT = "dependency_timeout"
    ELEVATED_5XX = "elevated_5xx"
    BAD_RELEASE = "bad_release"


@dataclass(frozen=True)
class ScenarioDefinition:
    """Immutable definition of a fault scenario."""

    key: ScenarioKey
    title: str
    description: str
    severity: str  # critical | high | medium
    expected_root_cause: str
    expected_evidence: list[str]
    allowed_fix: str
    default_ttl_seconds: int = 120
    parameters: dict[str, Any] = field(default_factory=dict)


# ── Built-in scenario catalogue ──────────────────────────────────────

SCENARIO_CATALOGUE: dict[ScenarioKey, ScenarioDefinition] = {
    ScenarioKey.DB_LATENCY: ScenarioDefinition(
        key=ScenarioKey.DB_LATENCY,
        title="Database Latency Spike",
        description=(
            "Adds a controlled delay (default 900ms) to the product query path. "
            "P95 latency rises from ~350ms to ~1.4s while error rates remain low."
        ),
        severity="high",
        expected_root_cause="Simulated database query delay on product listing",
        expected_evidence=[
            "Latency histogram shift on GET /products",
            "DB span dominates request duration",
            "No corresponding increase in 5xx error rate",
            "No recent release in change history",
        ],
        allowed_fix="disable_fault",
        default_ttl_seconds=120,
        parameters={"delay_ms": 900},
    ),
    ScenarioKey.DB_CONN_EXHAUSTION: ScenarioDefinition(
        key=ScenarioKey.DB_CONN_EXHAUSTION,
        title="Database Connection Pool Exhaustion",
        description=(
            "Lowers the simulated connection pool capacity, causing requests to "
            "fail with connection errors. Request failure rate rises sharply."
        ),
        severity="critical",
        expected_root_cause="Simulated connection pool exhaustion",
        expected_evidence=[
            "Connection timeout errors in logs",
            "Sharp increase in 5xx error rate",
            "Request failure rate correlates with pool size reduction",
        ],
        allowed_fix="disable_fault",
        default_ttl_seconds=90,
        parameters={"failure_rate": 0.7},
    ),
    ScenarioKey.DEPENDENCY_TIMEOUT: ScenarioDefinition(
        key=ScenarioKey.DEPENDENCY_TIMEOUT,
        title="Downstream Dependency Timeout",
        description=(
            "A fake shipping/payment dependency times out. Traces show the "
            "dependency span as the slow/error segment while ShopAPI itself is healthy."
        ),
        severity="high",
        expected_root_cause="Simulated downstream dependency timeout",
        expected_evidence=[
            "Dependency span dominates request duration",
            "ShopAPI core response time remains normal",
            "Timeout errors in trace spans for external calls",
        ],
        allowed_fix="disable_fault",
        default_ttl_seconds=120,
        parameters={"timeout_ms": 3000},
    ),
    ScenarioKey.ELEVATED_5XX: ScenarioDefinition(
        key=ScenarioKey.ELEVATED_5XX,
        title="Elevated 5xx Error Rate",
        description=(
            "Deterministic sampling returns HTTP 500 errors for a bounded "
            "interval. Logs and error-rate metrics correlate."
        ),
        severity="high",
        expected_root_cause="Simulated intermittent server errors",
        expected_evidence=[
            "Spike in 5xx error rate metrics",
            "Error logs with HTTP 500 status codes",
            "Error rate correlates with scenario activation time",
        ],
        allowed_fix="disable_fault",
        default_ttl_seconds=120,
        parameters={"error_rate": 0.4},
    ),
    ScenarioKey.BAD_RELEASE: ScenarioDefinition(
        key=ScenarioKey.BAD_RELEASE,
        title="Bad Release Deployment",
        description=(
            "A simulated release changes a query/config revision, producing "
            "slow product listing. Change history points to the release."
        ),
        severity="medium",
        expected_root_cause="Simulated bad release causing performance regression",
        expected_evidence=[
            "Latency increase on GET /products after release timestamp",
            "Change history shows a recent deployment",
            "No infrastructure-level issues in metrics",
        ],
        allowed_fix="restore_previous_config",
        default_ttl_seconds=180,
        parameters={"delay_ms": 600, "release_version": "v2.1.0-buggy"},
    ),
}


@dataclass
class ActiveFault:
    """Runtime state of a currently active fault scenario."""

    scenario_key: ScenarioKey
    started_at: float  # time.monotonic()
    started_at_utc: str  # ISO timestamp for display
    ttl_seconds: int
    parameters: dict[str, Any]

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.ttl_seconds - self.elapsed_seconds)

    @property
    def is_expired(self) -> bool:
        return self.elapsed_seconds >= self.ttl_seconds


class SimulatorState:
    """Thread-safe in-memory state for the fault simulator.

    Manages active faults, automatic TTL expiry, and safety caps.
    Only one instance of each scenario can be active at a time.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._active_faults: dict[ScenarioKey, ActiveFault] = {}
        self._change_history: list[dict[str, Any]] = []

    @property
    def active_faults(self) -> dict[ScenarioKey, ActiveFault]:
        """Return active (non-expired) faults, cleaning up expired ones."""
        self._cleanup_expired()
        return dict(self._active_faults)

    @property
    def change_history(self) -> list[dict[str, Any]]:
        """Return the deployment/config change history."""
        return list(self._change_history)

    def start_scenario(self, key: ScenarioKey) -> ActiveFault:
        """Activate a fault scenario.

        Raises ValueError if already active or simulator is disabled.
        """
        if not self._settings.simulator_enabled:
            raise ValueError("Simulator is disabled in this environment.")
        if not self._settings.is_development:
            raise ValueError("Simulator is only available in development mode.")

        self._cleanup_expired()

        if key in self._active_faults:
            raise ValueError(f"Scenario {key.value!r} is already active.")

        definition = SCENARIO_CATALOGUE[key]
        ttl = min(definition.default_ttl_seconds, self._settings.simulator_max_fault_seconds)

        from datetime import UTC, datetime

        fault = ActiveFault(
            scenario_key=key,
            started_at=time.monotonic(),
            started_at_utc=datetime.now(UTC).isoformat(),
            ttl_seconds=ttl,
            parameters=dict(definition.parameters),
        )
        self._active_faults[key] = fault

        # Record in change history if it's a "bad release" scenario
        if key == ScenarioKey.BAD_RELEASE:
            self._change_history.append(
                {
                    "type": "deployment",
                    "timestamp": fault.started_at_utc,
                    "service": "shopapi",
                    "version": definition.parameters.get("release_version", "unknown"),
                    "description": "Automated deployment of new release",
                    "author": "ci-pipeline",
                }
            )

        logger.info(
            "Scenario started",
            extra={
                "structured": {
                    "scenario": key.value,
                    "ttl_seconds": ttl,
                    "parameters": fault.parameters,
                }
            },
        )
        return fault

    def stop_scenario(self, key: ScenarioKey) -> None:
        """Stop an active scenario and clean up."""
        self._cleanup_expired()
        fault = self._active_faults.pop(key, None)
        if fault is None:
            raise ValueError(f"Scenario {key.value!r} is not active.")

        logger.info(
            "Scenario stopped",
            extra={
                "structured": {
                    "scenario": key.value,
                    "elapsed_seconds": round(fault.elapsed_seconds, 1),
                }
            },
        )

    def is_fault_active(self, key: ScenarioKey) -> bool:
        """Check if a specific fault is currently active (and not expired)."""
        self._cleanup_expired()
        return key in self._active_faults

    def get_fault(self, key: ScenarioKey) -> ActiveFault | None:
        """Get the active fault for a scenario, or None."""
        self._cleanup_expired()
        return self._active_faults.get(key)

    def get_fault_parameter(self, key: ScenarioKey, param: str, default: Any = None) -> Any:
        """Get a specific parameter from an active fault."""
        fault = self.get_fault(key)
        if fault is None:
            return default
        return fault.parameters.get(param, default)

    def stop_all(self) -> int:
        """Stop all active scenarios. Returns count of stopped faults."""
        self._cleanup_expired()
        count = len(self._active_faults)
        self._active_faults.clear()
        if count:
            logger.info(f"Stopped all {count} active scenarios")
        return count

    def _cleanup_expired(self) -> None:
        """Remove expired faults automatically."""
        expired = [k for k, f in self._active_faults.items() if f.is_expired]
        for key in expired:
            logger.info(
                "Scenario expired (TTL)",
                extra={"structured": {"scenario": key.value}},
            )
            self._active_faults.pop(key, None)


# ── Module-level singleton ────────────────────────────────────────────

_simulator: SimulatorState | None = None


def init_simulator(settings: Settings) -> SimulatorState:
    """Create the simulator singleton. Call once at startup."""
    global _simulator
    _simulator = SimulatorState(settings)
    return _simulator


def get_simulator() -> SimulatorState:
    """Return the simulator singleton, or raise if not initialised."""
    if _simulator is None:
        raise RuntimeError("Simulator not initialised — call init_simulator() first.")
    return _simulator

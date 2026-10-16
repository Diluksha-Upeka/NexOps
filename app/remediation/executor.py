"""Sandbox remediation executor — applies approved actions to simulator state.

This is ordinary application code, NOT a shell tool. Every execution:
1. Re-validates policy before mutating anything
2. Executes only allowlisted operations against the in-memory simulator
3. Records an audit trail with idempotency keys
4. Returns a typed result with success/failure and rollback instructions
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.remediation.catalog import ACTION_CATALOG
from app.remediation.policy import PolicyResult, evaluate_policy
from app.shopapi.simulator import ScenarioKey, SimulatorState

logger = logging.getLogger(__name__)


# ── Execution result ──────────────────────────────────────────────────


@dataclass
class ExecutionResult:
    """Typed outcome of a remediation execution attempt."""

    success: bool
    action_type: str
    idempotency_key: str
    executed_at: str
    status: str  # "success" | "denied" | "failed" | "no_op"
    details: dict[str, Any] = field(default_factory=dict)
    denial_code: str | None = None
    denial_reason: str | None = None
    error_message: str | None = None
    rollback_instruction: str | None = None


# ── Executor ──────────────────────────────────────────────────────────


class SandboxExecutor:
    """Executor that confines all mutations to the in-memory simulator.

    Each action is:
    - Policy-validated before execution
    - Idempotent via action+run key
    - Applied only to SimulatorState (no DB, no shell, no external calls)
    - Auditable with structured result
    """

    def __init__(self, simulator: SimulatorState) -> None:
        self._simulator = simulator
        self._applied_actions: list[dict[str, Any]] = []

    @property
    def applied_actions(self) -> list[dict[str, Any]]:
        """Return the history of applied actions for idempotency checking."""
        return list(self._applied_actions)

    def execute(
        self,
        *,
        action_type: str,
        parameters: dict[str, Any],
        approval_status: str | None,
        approval_incident_id: str | None = None,
        approval_run_id: str | None = None,
        current_incident_id: str,
        current_run_id: str,
        incident_status: str = "awaiting_approval",
        simulator_enabled: bool = True,
        is_development: bool = True,
        idempotency_key: str | None = None,
    ) -> ExecutionResult:
        """Execute a single remediation action with full policy pre-check.

        Returns an ExecutionResult that is never an exception — all
        outcomes including denials and failures are modelled as data.
        """
        resolved_key = idempotency_key or f"{action_type}-{current_run_id}-{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC).isoformat()

        # ── Step 1: Policy gate ───────────────────────────────────────
        policy: PolicyResult = evaluate_policy(
            action_type=action_type,
            parameters=parameters,
            approval_status=approval_status,
            approval_incident_id=approval_incident_id,
            approval_run_id=approval_run_id,
            current_incident_id=current_incident_id,
            current_run_id=current_run_id,
            incident_status=incident_status,
            simulator_enabled=simulator_enabled,
            is_development=is_development,
            idempotency_key=resolved_key,
            applied_actions=self._applied_actions,
        )

        if not policy.allowed:
            return ExecutionResult(
                success=False,
                action_type=action_type,
                idempotency_key=resolved_key,
                executed_at=now,
                status="denied",
                denial_code=policy.denial_code,
                denial_reason=policy.denial_reason,
            )

        # ── Step 2: Execute against simulator ─────────────────────────
        try:
            result = self._dispatch_action(action_type, parameters)
        except Exception as exc:
            logger.error(
                "Remediation execution failed",
                extra={
                    "structured": {
                        "action_type": action_type,
                        "error": str(exc),
                    }
                },
            )
            return ExecutionResult(
                success=False,
                action_type=action_type,
                idempotency_key=resolved_key,
                executed_at=now,
                status="failed",
                error_message=str(exc),
            )

        # ── Step 3: Record in applied history ─────────────────────────
        action_record = {
            "action_type": action_type,
            "parameters": parameters,
            "idempotency_key": resolved_key,
            "status": "success" if result.success else "failed",
            "executed_at": now,
            "incident_id": current_incident_id,
            "run_id": current_run_id,
        }
        self._applied_actions.append(action_record)

        logger.info(
            "Remediation action executed",
            extra={
                "structured": {
                    "action_type": action_type,
                    "status": result.status,
                    "idempotency_key": resolved_key,
                }
            },
        )
        return result

    def _dispatch_action(
        self,
        action_type: str,
        parameters: dict[str, Any],
    ) -> ExecutionResult:
        """Route to the appropriate simulator mutation handler."""
        now = datetime.now(UTC).isoformat()
        idem_key = f"{action_type}-dispatch"

        if action_type == "disable_fault":
            return self._execute_disable_fault(parameters)
        elif action_type == "rollback_release":
            return self._execute_rollback_release(parameters)
        elif action_type == "scale_pool":
            return self._execute_scale_pool(parameters)
        else:
            return ExecutionResult(
                success=False,
                action_type=action_type,
                idempotency_key=idem_key,
                executed_at=now,
                status="failed",
                error_message=f"No executor handler for action type '{action_type}'.",
            )

    def _execute_disable_fault(self, parameters: dict[str, Any]) -> ExecutionResult:
        """Disable an active fault scenario on the simulator."""
        now = datetime.now(UTC).isoformat()
        scenario_key_str = parameters.get("scenario_key", "")

        # Map cause keys to actual ScenarioKey values
        key_mapping: dict[str, ScenarioKey] = {
            "db_latency": ScenarioKey.DB_LATENCY,
            "db_connection_exhaustion": ScenarioKey.DB_CONN_EXHAUSTION,
            "db_conn_exhaustion": ScenarioKey.DB_CONN_EXHAUSTION,
            "dependency_timeout": ScenarioKey.DEPENDENCY_TIMEOUT,
            "elevated_5xx": ScenarioKey.ELEVATED_5XX,
            "bad_release": ScenarioKey.BAD_RELEASE,
        }

        scenario_key = key_mapping.get(scenario_key_str)
        if scenario_key is None:
            # Try direct enum match
            try:
                scenario_key = ScenarioKey(scenario_key_str)
            except ValueError:
                return ExecutionResult(
                    success=False,
                    action_type="disable_fault",
                    idempotency_key=f"disable_fault-{scenario_key_str}",
                    executed_at=now,
                    status="failed",
                    error_message=f"Unknown scenario key: '{scenario_key_str}'",
                )

        # Check if fault is actually active
        if not self._simulator.is_fault_active(scenario_key):
            action_def = ACTION_CATALOG.get("disable_fault")
            return ExecutionResult(
                success=True,
                action_type="disable_fault",
                idempotency_key=f"disable_fault-{scenario_key_str}",
                executed_at=now,
                status="no_op",
                details={
                    "scenario_key": scenario_key_str,
                    "message": (
                        f"Fault '{scenario_key_str}' is not currently active (may have expired)."
                    ),
                },
                rollback_instruction=(
                    f"Fault was not active; no rollback needed. "
                    f"To restart: start scenario '{scenario_key.value}'"
                ),
            )

        # Execute the mutation
        self._simulator.stop_scenario(scenario_key)

        action_def = ACTION_CATALOG.get("disable_fault")
        rollback_action = action_def.default_rollback_action if action_def else "restart_fault"
        return ExecutionResult(
            success=True,
            action_type="disable_fault",
            idempotency_key=f"disable_fault-{scenario_key_str}",
            executed_at=now,
            status="success",
            details={
                "scenario_key": scenario_key_str,
                "message": f"Fault '{scenario_key_str}' has been disabled on the simulator.",
            },
            rollback_instruction=(
                f"To undo: restart scenario '{scenario_key.value}' via simulator API. "
                f"Rollback action: {rollback_action}"
            ),
        )

    def _execute_rollback_release(self, parameters: dict[str, Any]) -> ExecutionResult:
        """Roll back a simulated bad release by disabling its fault."""
        now = datetime.now(UTC).isoformat()
        target_revision = parameters.get("target_revision", "previous_stable")

        # A rollback in our simulator means stopping the bad_release fault
        scenario_key = ScenarioKey.BAD_RELEASE

        if not self._simulator.is_fault_active(scenario_key):
            return ExecutionResult(
                success=True,
                action_type="rollback_release",
                idempotency_key=f"rollback_release-{target_revision}",
                executed_at=now,
                status="no_op",
                details={
                    "target_revision": target_revision,
                    "message": (
                        "Bad release fault is not active (may have expired or been rolled back)."
                    ),
                },
            )

        self._simulator.stop_scenario(scenario_key)

        return ExecutionResult(
            success=True,
            action_type="rollback_release",
            idempotency_key=f"rollback_release-{target_revision}",
            executed_at=now,
            status="success",
            details={
                "target_revision": target_revision,
                "message": (
                    f"Simulated release rolled back to '{target_revision}'. "
                    "Bad release fault has been stopped."
                ),
            },
            rollback_instruction=(
                "To undo: restart the 'bad_release' scenario via simulator API. "
                "Rollback action: reapply_revision"
            ),
        )

    def _execute_scale_pool(self, parameters: dict[str, Any]) -> ExecutionResult:
        """Simulate increasing the connection pool size."""
        now = datetime.now(UTC).isoformat()
        target_pool_size = parameters.get("target_pool_size", 20)

        # In our sandbox, scaling the pool means disabling the exhaustion fault
        scenario_key = ScenarioKey.DB_CONN_EXHAUSTION

        if not self._simulator.is_fault_active(scenario_key):
            return ExecutionResult(
                success=True,
                action_type="scale_pool",
                idempotency_key=f"scale_pool-{target_pool_size}",
                executed_at=now,
                status="no_op",
                details={
                    "target_pool_size": target_pool_size,
                    "message": "Connection exhaustion fault is not active.",
                },
            )

        self._simulator.stop_scenario(scenario_key)

        return ExecutionResult(
            success=True,
            action_type="scale_pool",
            idempotency_key=f"scale_pool-{target_pool_size}",
            executed_at=now,
            status="success",
            details={
                "target_pool_size": target_pool_size,
                "message": (
                    f"Simulated pool scaled to {target_pool_size} connections. "
                    "Connection exhaustion fault disabled."
                ),
            },
            rollback_instruction=(
                "To undo: restart 'db_conn_exhaustion' scenario. Rollback action: restore_pool_size"
            ),
        )

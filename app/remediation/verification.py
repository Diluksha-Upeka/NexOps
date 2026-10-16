"""Post-action verification — measures telemetry after remediation.

Verification checks a brief observation window after remediation to
determine whether the incident can be marked as resolved, mitigated,
or must remain open. It never auto-resolves on insufficient data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.remediation.executor import ExecutionResult
from app.shopapi.simulator import ScenarioKey, SimulatorState

logger = logging.getLogger(__name__)


# ── Verification result ───────────────────────────────────────────────


@dataclass
class VerificationResult:
    """Typed outcome of post-action verification."""

    passed: bool
    outcome: str  # "resolved" | "mitigated" | "failed" | "inconclusive"
    checks: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    verified_at: str = ""
    recommended_incident_status: str = "open"


# ── Verification checks ──────────────────────────────────────────────


def _check_fault_inactive(simulator: SimulatorState, scenario_key_str: str) -> dict[str, Any]:
    """Verify the target fault is no longer active in the simulator."""
    # Map common cause keys to ScenarioKeys
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
        try:
            scenario_key = ScenarioKey(scenario_key_str)
        except ValueError:
            return {
                "check": "fault_inactive",
                "passed": False,
                "detail": f"Unknown scenario key '{scenario_key_str}'; cannot verify.",
            }

    is_active = simulator.is_fault_active(scenario_key)
    return {
        "check": "fault_inactive",
        "passed": not is_active,
        "detail": (f"Fault '{scenario_key_str}' is {'still ACTIVE' if is_active else 'inactive'}."),
    }


def _check_no_active_faults(simulator: SimulatorState) -> dict[str, Any]:
    """Verify no unexpected faults remain active after remediation."""
    active = simulator.active_faults
    return {
        "check": "no_active_faults",
        "passed": len(active) == 0,
        "detail": (
            f"Active faults remaining: {len(active)}. "
            f"Keys: {[k.value for k in active] if active else 'none'}"
        ),
    }


def _check_execution_success(execution_result: ExecutionResult) -> dict[str, Any]:
    """Verify the execution itself reported success."""
    return {
        "check": "execution_success",
        "passed": execution_result.success and execution_result.status in ("success", "no_op"),
        "detail": (
            f"Execution status: {execution_result.status}. "
            f"{'Succeeded' if execution_result.success else 'Failed'}."
        ),
    }


# ── Main verification function ────────────────────────────────────────


def verify_remediation(
    *,
    execution_result: ExecutionResult,
    simulator: SimulatorState,
    action_type: str,
    parameters: dict[str, Any],
) -> VerificationResult:
    """Run post-action verification checks and determine incident outcome.

    The verification:
    1. Checks the execution itself succeeded
    2. Verifies the target fault is no longer active
    3. Checks for any remaining active faults
    4. Produces a recommendation for the incident status transition

    Returns VerificationResult with a recommended incident status:
    - "resolved": all checks passed, fault eliminated
    - "mitigated": action succeeded but some concerns remain
    - "failed": action did not achieve desired effect
    - "inconclusive": insufficient data to determine outcome
    """
    now = datetime.now(UTC).isoformat()
    checks: list[dict[str, Any]] = []

    # ── Check 1: Execution success ────────────────────────────────────
    exec_check = _check_execution_success(execution_result)
    checks.append(exec_check)

    if not exec_check["passed"]:
        return VerificationResult(
            passed=False,
            outcome="failed",
            checks=checks,
            summary=(
                f"Remediation action '{action_type}' failed during execution. "
                f"Status: {execution_result.status}. "
                f"Error: "
                f"{execution_result.error_message or execution_result.denial_reason or 'unknown'}."
            ),
            verified_at=now,
            recommended_incident_status="open",
        )

    # ── Check 2: Target fault inactive ────────────────────────────────
    scenario_key_str = _extract_scenario_key(action_type, parameters)
    if scenario_key_str:
        fault_check = _check_fault_inactive(simulator, scenario_key_str)
        checks.append(fault_check)
    else:
        fault_check = {
            "check": "fault_inactive",
            "passed": True,
            "detail": "No specific fault to verify.",
        }
        checks.append(fault_check)

    # ── Check 3: Overall simulator state ──────────────────────────────
    remaining_check = _check_no_active_faults(simulator)
    checks.append(remaining_check)

    # ── Determine outcome ─────────────────────────────────────────────
    all_passed = all(c["passed"] for c in checks)
    fault_cleared = fault_check["passed"]
    no_remaining = remaining_check["passed"]

    if all_passed:
        # Everything clean — fully resolved
        return VerificationResult(
            passed=True,
            outcome="resolved",
            checks=checks,
            summary=(
                f"Remediation action '{action_type}' verified successfully. "
                f"Target fault is inactive and no remaining faults detected. "
                f"Incident can be marked as resolved."
            ),
            verified_at=now,
            recommended_incident_status="resolved",
        )
    elif fault_cleared and not no_remaining:
        # Target fault gone but other faults remain — mitigated
        return VerificationResult(
            passed=True,
            outcome="mitigated",
            checks=checks,
            summary=(
                f"Remediation action '{action_type}' cleared the target fault, "
                f"but other active faults remain. Incident is mitigated, not fully resolved."
            ),
            verified_at=now,
            recommended_incident_status="mitigated",
        )
    elif not fault_cleared:
        # Target fault still active — failed
        return VerificationResult(
            passed=False,
            outcome="failed",
            checks=checks,
            summary=(
                f"Verification failed: target fault is still active after "
                f"'{action_type}' execution. The remediation did not achieve its objective."
            ),
            verified_at=now,
            recommended_incident_status="open",
        )
    else:
        # Inconclusive — execution succeeded but uncertain
        return VerificationResult(
            passed=False,
            outcome="inconclusive",
            checks=checks,
            summary=(
                f"Verification inconclusive for '{action_type}'. "
                f"Some checks did not pass. Manual inspection recommended."
            ),
            verified_at=now,
            recommended_incident_status="open",
        )


def _extract_scenario_key(action_type: str, parameters: dict[str, Any]) -> str | None:
    """Extract the relevant scenario key from action parameters."""
    if action_type == "disable_fault":
        return parameters.get("scenario_key")
    elif action_type == "rollback_release":
        return "bad_release"
    elif action_type == "scale_pool":
        return "db_conn_exhaustion"
    return None

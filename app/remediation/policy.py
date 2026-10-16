"""Remediation policy engine — validates preconditions before execution.

Every proposed action must pass all policy checks before the executor
is allowed to mutate simulator state.  Denials are recorded with typed
reason codes; no secrets or internal details are leaked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.remediation.catalog import ACTION_CATALOG, RemediationActionDefinition

logger = logging.getLogger(__name__)


# ── Policy result ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class PolicyResult:
    """Outcome of a policy evaluation."""

    allowed: bool
    denial_code: str | None = None
    denial_reason: str | None = None


# ── Denial codes ──────────────────────────────────────────────────────

DENIAL_MISSING_APPROVAL = "missing_approval"
DENIAL_APPROVAL_NOT_APPROVED = "approval_not_approved"
DENIAL_STALE_APPROVAL = "stale_approval"
DENIAL_ACTION_NOT_ALLOWLISTED = "action_not_allowlisted"
DENIAL_SIMULATOR_DISABLED = "simulator_disabled"
DENIAL_NOT_DEVELOPMENT = "not_development_mode"
DENIAL_PARAMETER_VIOLATION = "parameter_violation"
DENIAL_INCIDENT_RUN_MISMATCH = "incident_run_mismatch"
DENIAL_ALREADY_APPLIED = "action_already_applied"
DENIAL_INVALID_INCIDENT_STATE = "invalid_incident_state"


# ── Policy check functions ────────────────────────────────────────────


def check_action_allowlisted(action_type: str) -> PolicyResult:
    """Verify the action type exists in the fixed catalog."""
    if action_type not in ACTION_CATALOG:
        return PolicyResult(
            allowed=False,
            denial_code=DENIAL_ACTION_NOT_ALLOWLISTED,
            denial_reason=f"Action type '{action_type}' is not in the allowlisted catalog.",
        )
    return PolicyResult(allowed=True)


def check_approval_status(
    approval_status: str | None,
) -> PolicyResult:
    """Verify the approval has been explicitly granted."""
    if not approval_status:
        return PolicyResult(
            allowed=False,
            denial_code=DENIAL_MISSING_APPROVAL,
            denial_reason="No approval record found for this remediation action.",
        )
    if approval_status != "approved":
        return PolicyResult(
            allowed=False,
            denial_code=DENIAL_APPROVAL_NOT_APPROVED,
            denial_reason=f"Approval status is '{approval_status}', not 'approved'.",
        )
    return PolicyResult(allowed=True)


def check_simulator_mode(
    *,
    simulator_enabled: bool,
    is_development: bool,
) -> PolicyResult:
    """Verify the simulator is enabled and we are in development mode."""
    if not simulator_enabled:
        return PolicyResult(
            allowed=False,
            denial_code=DENIAL_SIMULATOR_DISABLED,
            denial_reason="Simulator is disabled in the current environment.",
        )
    if not is_development:
        return PolicyResult(
            allowed=False,
            denial_code=DENIAL_NOT_DEVELOPMENT,
            denial_reason="Remediation actions require development mode.",
        )
    return PolicyResult(allowed=True)


def check_parameters(
    action_def: RemediationActionDefinition,
    parameters: dict[str, Any],
) -> PolicyResult:
    """Validate that all supplied parameters are within allowed set and bounds."""
    allowed_params = set(action_def.allowed_parameters)
    for key in parameters:
        if key not in allowed_params:
            return PolicyResult(
                allowed=False,
                denial_code=DENIAL_PARAMETER_VIOLATION,
                denial_reason=(
                    f"Parameter '{key}' is not allowed for action '{action_def.action_type}'. "
                    f"Allowed: {sorted(allowed_params)}"
                ),
            )

    # Bounds check: pool size must be positive and capped
    if "target_pool_size" in parameters:
        pool_size = parameters["target_pool_size"]
        if not isinstance(pool_size, int) or pool_size < 1 or pool_size > 100:
            return PolicyResult(
                allowed=False,
                denial_code=DENIAL_PARAMETER_VIOLATION,
                denial_reason=(
                    f"target_pool_size must be an integer between 1 and 100, got {pool_size}."
                ),
            )

    return PolicyResult(allowed=True)


def check_incident_run_consistency(
    *,
    approval_incident_id: str | None,
    approval_run_id: str | None,
    current_incident_id: str,
    current_run_id: str,
) -> PolicyResult:
    """Verify the approval belongs to the current incident and run."""
    if approval_incident_id and approval_incident_id != current_incident_id:
        return PolicyResult(
            allowed=False,
            denial_code=DENIAL_INCIDENT_RUN_MISMATCH,
            denial_reason="Approval belongs to a different incident.",
        )
    if approval_run_id and approval_run_id != current_run_id:
        return PolicyResult(
            allowed=False,
            denial_code=DENIAL_INCIDENT_RUN_MISMATCH,
            denial_reason="Approval belongs to a different investigation run.",
        )
    return PolicyResult(allowed=True)


def check_incident_state(incident_status: str) -> PolicyResult:
    """Verify the incident is in a state that allows remediation."""
    # Only allow remediation when incident is transitioning to or in remediating state
    allowed_states = {"investigating", "awaiting_approval", "remediating"}
    if incident_status not in allowed_states:
        return PolicyResult(
            allowed=False,
            denial_code=DENIAL_INVALID_INCIDENT_STATE,
            denial_reason=(
                f"Incident status '{incident_status}' does not allow remediation. "
                f"Allowed: {sorted(allowed_states)}"
            ),
        )
    return PolicyResult(allowed=True)


def check_not_already_applied(
    *,
    action_type: str,
    idempotency_key: str | None,
    applied_actions: list[dict[str, Any]] | None = None,
) -> PolicyResult:
    """Prevent duplicate execution of the same remediation action."""
    if not applied_actions:
        return PolicyResult(allowed=True)

    for applied in applied_actions:
        if idempotency_key and applied.get("idempotency_key") == idempotency_key:
            return PolicyResult(
                allowed=False,
                denial_code=DENIAL_ALREADY_APPLIED,
                denial_reason=(
                    f"Action with idempotency key '{idempotency_key}' was already applied."
                ),
            )
        # Also catch duplicate action_type applied in the same run
        if applied.get("action_type") == action_type and applied.get("status") == "success":
            return PolicyResult(
                allowed=False,
                denial_code=DENIAL_ALREADY_APPLIED,
                denial_reason=(
                    f"Action '{action_type}' was already successfully applied in this run."
                ),
            )

    return PolicyResult(allowed=True)


# ── Full policy evaluation ────────────────────────────────────────────


def evaluate_policy(
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
    applied_actions: list[dict[str, Any]] | None = None,
) -> PolicyResult:
    """Run all policy checks and return the first denial, or allow.

    This is the single entry point for remediation policy evaluation.
    Each check is run in priority order; the first failure is returned.
    """
    checks: list[PolicyResult] = [
        check_approval_status(approval_status),
        check_action_allowlisted(action_type),
        check_simulator_mode(
            simulator_enabled=simulator_enabled,
            is_development=is_development,
        ),
        check_incident_state(incident_status),
        check_incident_run_consistency(
            approval_incident_id=approval_incident_id,
            approval_run_id=approval_run_id,
            current_incident_id=current_incident_id,
            current_run_id=current_run_id,
        ),
        check_not_already_applied(
            action_type=action_type,
            idempotency_key=idempotency_key,
            applied_actions=applied_actions,
        ),
    ]

    for result in checks:
        if not result.allowed:
            logger.warning(
                "Policy denied remediation",
                extra={
                    "structured": {
                        "action_type": action_type,
                        "denial_code": result.denial_code,
                        "denial_reason": result.denial_reason,
                    }
                },
            )
            return result

    # Parameter validation requires the action definition
    action_def = ACTION_CATALOG.get(action_type)
    if action_def:
        param_result = check_parameters(action_def, parameters)
        if not param_result.allowed:
            logger.warning(
                "Policy denied remediation (parameter violation)",
                extra={
                    "structured": {
                        "action_type": action_type,
                        "denial_code": param_result.denial_code,
                    }
                },
            )
            return param_result

    logger.info(
        "Policy approved remediation",
        extra={"structured": {"action_type": action_type}},
    )
    return PolicyResult(allowed=True)

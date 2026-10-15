"""Allowlisted action catalog for incident remediation.

Remediation actions are strictly allowlisted, parameterized, and
confined to simulator state.  No arbitrary execution, shell commands,
or external mutations are permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RemediationActionDefinition:
    """Definition of an allowlisted remediation action."""

    action_type: str
    description: str
    allowed_parameters: list[str]
    risk_level: str  # "low" | "medium" | "high"
    default_rollback_action: str
    verification_query: str


# ── Action Catalog ────────────────────────────────────────────────────

ACTION_CATALOG: dict[str, RemediationActionDefinition] = {
    "disable_fault": RemediationActionDefinition(
        action_type="disable_fault",
        description="Stop an active fault injection scenario on the simulator.",
        allowed_parameters=["scenario_key"],
        risk_level="low",
        default_rollback_action="restart_fault",
        verification_query="metrics:request_duration:p95 < 400ms AND error_rate < 0.01",
    ),
    "rollback_release": RemediationActionDefinition(
        action_type="rollback_release",
        description="Roll back simulated configuration/deployment to the previous stable revision.",
        allowed_parameters=["service", "target_revision"],
        risk_level="medium",
        default_rollback_action="reapply_revision",
        verification_query="changes:latest.status == 'rolled_back' AND error_rate < 0.01",
    ),
    "scale_pool": RemediationActionDefinition(
        action_type="scale_pool",
        description="Increase simulated connection pool capacity to relieve resource exhaustion.",
        allowed_parameters=["service", "target_pool_size"],
        risk_level="medium",
        default_rollback_action="restore_pool_size",
        verification_query="logs:error_count == 0 AND metrics:active_connections < capacity",
    ),
}

# Mapping of root cause keys to catalog action types
CAUSE_TO_ACTION: dict[str, str] = {
    "db_latency": "disable_fault",
    "db_connection_exhaustion": "disable_fault",
    "bad_release": "rollback_release",
    "dependency_timeout": "disable_fault",
    "elevated_5xx": "disable_fault",
}


def get_action_definition(action_type: str) -> RemediationActionDefinition | None:
    """Lookup an action definition by type."""
    return ACTION_CATALOG.get(action_type)


def map_cause_to_action(cause_key: str, scenario_key: str | None = None) -> dict[str, Any] | None:
    """Map a diagnosed root cause to an allowlisted action recommendation."""
    action_type = CAUSE_TO_ACTION.get(cause_key)
    if not action_type:
        return None

    action_def = ACTION_CATALOG.get(action_type)
    if not action_def:
        return None

    # Derive parameters safely
    parameters: dict[str, Any] = {}
    if action_type == "disable_fault":
        parameters["scenario_key"] = scenario_key or cause_key
    elif action_type == "rollback_release":
        parameters["service"] = "shopapi"
        parameters["target_revision"] = "previous_stable"
    elif action_type == "scale_pool":
        parameters["service"] = "shopapi"
        parameters["target_pool_size"] = 20

    return {
        "action_type": action_type,
        "parameters": parameters,
        "description": action_def.description,
        "risk_level": action_def.risk_level,
        "rollback_plan": f"Execute {action_def.default_rollback_action} if verification fails.",
        "verification_plan": f"Verify via: {action_def.verification_query}",
    }

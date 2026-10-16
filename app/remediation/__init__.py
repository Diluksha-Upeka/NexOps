"""Remediation policy, sandbox executor, verification (Phase 6).

This package provides the complete remediation pipeline:
- catalog.py: Fixed allowlisted action catalog
- policy.py: Pre-execution policy checks
- executor.py: Sandbox executor confined to simulator state
- verification.py: Post-action verification and outcome determination
"""

from app.remediation.catalog import (
    ACTION_CATALOG,
    CAUSE_TO_ACTION,
    RemediationActionDefinition,
    get_action_definition,
    map_cause_to_action,
)
from app.remediation.executor import ExecutionResult, SandboxExecutor
from app.remediation.policy import PolicyResult, evaluate_policy
from app.remediation.verification import VerificationResult, verify_remediation

__all__ = [
    "ACTION_CATALOG",
    "CAUSE_TO_ACTION",
    "ExecutionResult",
    "PolicyResult",
    "RemediationActionDefinition",
    "SandboxExecutor",
    "VerificationResult",
    "evaluate_policy",
    "get_action_definition",
    "map_cause_to_action",
    "verify_remediation",
]

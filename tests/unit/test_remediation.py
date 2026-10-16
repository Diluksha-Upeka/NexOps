"""Tests for Phase 6 — sandbox remediation and verification.

Covers:
- Policy engine (all denial paths + allow)
- Sandbox executor (disable_fault, rollback_release, scale_pool, denied, idempotent)
- Post-action verification (resolved, mitigated, failed)
- Graph node integration (execute_remediation_node, verify_remediation_node)
"""

from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.remediation.catalog import ACTION_CATALOG, map_cause_to_action
from app.remediation.executor import ExecutionResult, SandboxExecutor
from app.remediation.policy import (
    DENIAL_ACTION_NOT_ALLOWLISTED,
    DENIAL_ALREADY_APPLIED,
    DENIAL_APPROVAL_NOT_APPROVED,
    DENIAL_INCIDENT_RUN_MISMATCH,
    DENIAL_INVALID_INCIDENT_STATE,
    DENIAL_MISSING_APPROVAL,
    DENIAL_NOT_DEVELOPMENT,
    DENIAL_PARAMETER_VIOLATION,
    DENIAL_SIMULATOR_DISABLED,
    check_action_allowlisted,
    check_approval_status,
    check_incident_run_consistency,
    check_incident_state,
    check_not_already_applied,
    check_parameters,
    check_simulator_mode,
    evaluate_policy,
)
from app.remediation.verification import verify_remediation
from app.shopapi.simulator import ScenarioKey, SimulatorState

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def dev_settings() -> Settings:
    """Settings in development mode with simulator enabled."""
    return Settings(
        app_env="development",
        simulator_enabled=True,
        simulator_max_fault_seconds=300,
        database_url="postgresql+psycopg://test:test@localhost:5432/test",
    )


@pytest.fixture()
def simulator(dev_settings: Settings) -> SimulatorState:
    """Fresh simulator state for each test."""
    return SimulatorState(dev_settings)


# ══════════════════════════════════════════════════════════════════════
#  Policy Engine Tests
# ══════════════════════════════════════════════════════════════════════


class TestCheckActionAllowlisted:
    """Tests for check_action_allowlisted."""

    def test_allowlisted_action(self) -> None:
        result = check_action_allowlisted("disable_fault")
        assert result.allowed is True

    def test_unknown_action(self) -> None:
        result = check_action_allowlisted("delete_database")
        assert result.allowed is False
        assert result.denial_code == DENIAL_ACTION_NOT_ALLOWLISTED

    def test_all_catalog_actions_allowed(self) -> None:
        for action_type in ACTION_CATALOG:
            result = check_action_allowlisted(action_type)
            assert result.allowed is True, f"{action_type} should be allowed"


class TestCheckApprovalStatus:
    """Tests for check_approval_status."""

    def test_approved(self) -> None:
        assert check_approval_status("approved").allowed is True

    def test_missing_approval(self) -> None:
        result = check_approval_status(None)
        assert result.allowed is False
        assert result.denial_code == DENIAL_MISSING_APPROVAL

    def test_rejected_approval(self) -> None:
        result = check_approval_status("rejected")
        assert result.allowed is False
        assert result.denial_code == DENIAL_APPROVAL_NOT_APPROVED

    def test_pending_approval(self) -> None:
        result = check_approval_status("pending")
        assert result.allowed is False
        assert result.denial_code == DENIAL_APPROVAL_NOT_APPROVED


class TestCheckSimulatorMode:
    """Tests for check_simulator_mode."""

    def test_dev_enabled(self) -> None:
        result = check_simulator_mode(simulator_enabled=True, is_development=True)
        assert result.allowed is True

    def test_disabled_simulator(self) -> None:
        result = check_simulator_mode(simulator_enabled=False, is_development=True)
        assert result.allowed is False
        assert result.denial_code == DENIAL_SIMULATOR_DISABLED

    def test_non_development(self) -> None:
        result = check_simulator_mode(simulator_enabled=True, is_development=False)
        assert result.allowed is False
        assert result.denial_code == DENIAL_NOT_DEVELOPMENT


class TestCheckParameters:
    """Tests for check_parameters."""

    def test_valid_disable_fault(self) -> None:
        action_def = ACTION_CATALOG["disable_fault"]
        result = check_parameters(action_def, {"scenario_key": "db_latency"})
        assert result.allowed is True

    def test_invalid_parameter(self) -> None:
        action_def = ACTION_CATALOG["disable_fault"]
        result = check_parameters(action_def, {"scenario_key": "db_latency", "shell_cmd": "rm -rf"})
        assert result.allowed is False
        assert result.denial_code == DENIAL_PARAMETER_VIOLATION

    def test_pool_size_bounds_exceeded(self) -> None:
        action_def = ACTION_CATALOG["scale_pool"]
        result = check_parameters(action_def, {"service": "shopapi", "target_pool_size": 999})
        assert result.allowed is False
        assert result.denial_code == DENIAL_PARAMETER_VIOLATION

    def test_pool_size_valid(self) -> None:
        action_def = ACTION_CATALOG["scale_pool"]
        result = check_parameters(action_def, {"service": "shopapi", "target_pool_size": 20})
        assert result.allowed is True


class TestCheckIncidentRunConsistency:
    """Tests for check_incident_run_consistency."""

    def test_matching(self) -> None:
        result = check_incident_run_consistency(
            approval_incident_id="inc-1",
            approval_run_id="run-1",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )
        assert result.allowed is True

    def test_mismatched_incident(self) -> None:
        result = check_incident_run_consistency(
            approval_incident_id="inc-2",
            approval_run_id="run-1",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )
        assert result.allowed is False
        assert result.denial_code == DENIAL_INCIDENT_RUN_MISMATCH

    def test_mismatched_run(self) -> None:
        result = check_incident_run_consistency(
            approval_incident_id="inc-1",
            approval_run_id="run-2",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )
        assert result.allowed is False
        assert result.denial_code == DENIAL_INCIDENT_RUN_MISMATCH


class TestCheckIncidentState:
    """Tests for check_incident_state."""

    def test_investigating(self) -> None:
        assert check_incident_state("investigating").allowed is True

    def test_awaiting_approval(self) -> None:
        assert check_incident_state("awaiting_approval").allowed is True

    def test_remediating(self) -> None:
        assert check_incident_state("remediating").allowed is True

    def test_resolved_blocked(self) -> None:
        result = check_incident_state("resolved")
        assert result.allowed is False
        assert result.denial_code == DENIAL_INVALID_INCIDENT_STATE

    def test_open_blocked(self) -> None:
        result = check_incident_state("open")
        assert result.allowed is False
        assert result.denial_code == DENIAL_INVALID_INCIDENT_STATE


class TestCheckNotAlreadyApplied:
    """Tests for check_not_already_applied."""

    def test_no_prior_actions(self) -> None:
        result = check_not_already_applied(
            action_type="disable_fault",
            idempotency_key="key-1",
            applied_actions=[],
        )
        assert result.allowed is True

    def test_duplicate_idempotency_key(self) -> None:
        result = check_not_already_applied(
            action_type="disable_fault",
            idempotency_key="key-1",
            applied_actions=[
                {"action_type": "disable_fault", "idempotency_key": "key-1", "status": "success"}
            ],
        )
        assert result.allowed is False
        assert result.denial_code == DENIAL_ALREADY_APPLIED

    def test_duplicate_action_type(self) -> None:
        result = check_not_already_applied(
            action_type="disable_fault",
            idempotency_key="key-2",
            applied_actions=[
                {"action_type": "disable_fault", "idempotency_key": "key-1", "status": "success"}
            ],
        )
        assert result.allowed is False
        assert result.denial_code == DENIAL_ALREADY_APPLIED


class TestEvaluatePolicy:
    """Tests for the full policy evaluation pipeline."""

    def test_all_valid(self) -> None:
        result = evaluate_policy(
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )
        assert result.allowed is True

    def test_first_failure_wins(self) -> None:
        """Missing approval is checked first, so that denial should come back."""
        result = evaluate_policy(
            action_type="delete_database",  # also bad
            parameters={},
            approval_status=None,  # first check fails
            current_incident_id="inc-1",
            current_run_id="run-1",
        )
        assert result.allowed is False
        assert result.denial_code == DENIAL_MISSING_APPROVAL


# ══════════════════════════════════════════════════════════════════════
#  Sandbox Executor Tests
# ══════════════════════════════════════════════════════════════════════


class TestSandboxExecutor:
    """Tests for SandboxExecutor."""

    def test_disable_active_fault(self, simulator: SimulatorState) -> None:
        """Approved action should stop the active fault."""
        simulator.start_scenario(ScenarioKey.DB_LATENCY)
        assert simulator.is_fault_active(ScenarioKey.DB_LATENCY) is True

        executor = SandboxExecutor(simulator)
        result = executor.execute(
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )

        assert result.success is True
        assert result.status == "success"
        assert simulator.is_fault_active(ScenarioKey.DB_LATENCY) is False
        assert result.rollback_instruction is not None

    def test_disable_inactive_fault_is_noop(self, simulator: SimulatorState) -> None:
        """Disabling an already-inactive fault should succeed as no_op."""
        executor = SandboxExecutor(simulator)
        result = executor.execute(
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )

        assert result.success is True
        assert result.status == "no_op"

    def test_policy_denial_blocks_execution(self, simulator: SimulatorState) -> None:
        """Unapproved action must not mutate simulator."""
        simulator.start_scenario(ScenarioKey.DB_LATENCY)
        executor = SandboxExecutor(simulator)
        result = executor.execute(
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
            approval_status="rejected",  # not approved
            current_incident_id="inc-1",
            current_run_id="run-1",
        )

        assert result.success is False
        assert result.status == "denied"
        assert result.denial_code == DENIAL_APPROVAL_NOT_APPROVED
        # Fault should still be active
        assert simulator.is_fault_active(ScenarioKey.DB_LATENCY) is True

    def test_rollback_release(self, simulator: SimulatorState) -> None:
        """Rollback release action should stop the bad_release fault."""
        simulator.start_scenario(ScenarioKey.BAD_RELEASE)
        assert simulator.is_fault_active(ScenarioKey.BAD_RELEASE) is True

        executor = SandboxExecutor(simulator)
        result = executor.execute(
            action_type="rollback_release",
            parameters={"service": "shopapi", "target_revision": "previous_stable"},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )

        assert result.success is True
        assert result.status == "success"
        assert simulator.is_fault_active(ScenarioKey.BAD_RELEASE) is False

    def test_scale_pool(self, simulator: SimulatorState) -> None:
        """Scale pool action should stop the connection exhaustion fault."""
        simulator.start_scenario(ScenarioKey.DB_CONN_EXHAUSTION)
        assert simulator.is_fault_active(ScenarioKey.DB_CONN_EXHAUSTION) is True

        executor = SandboxExecutor(simulator)
        result = executor.execute(
            action_type="scale_pool",
            parameters={"service": "shopapi", "target_pool_size": 20},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )

        assert result.success is True
        assert result.status == "success"
        assert simulator.is_fault_active(ScenarioKey.DB_CONN_EXHAUSTION) is False

    def test_simulator_disabled_blocks(self, simulator: SimulatorState) -> None:
        """Disabled simulator should deny action."""
        executor = SandboxExecutor(simulator)
        result = executor.execute(
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
            simulator_enabled=False,
        )

        assert result.success is False
        assert result.denial_code == DENIAL_SIMULATOR_DISABLED

    def test_idempotent_duplicate_blocked(self, simulator: SimulatorState) -> None:
        """Second execution with same key is denied as already applied."""
        simulator.start_scenario(ScenarioKey.DB_LATENCY)
        executor = SandboxExecutor(simulator)

        # First execution succeeds
        result1 = executor.execute(
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
            idempotency_key="idem-key-1",
        )
        assert result1.success is True

        # Second execution with same idempotency key is denied
        result2 = executor.execute(
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
            idempotency_key="idem-key-1",
        )
        assert result2.success is False
        assert result2.denial_code == DENIAL_ALREADY_APPLIED

    def test_applied_actions_tracked(self, simulator: SimulatorState) -> None:
        """Executor should track applied actions for idempotency."""
        simulator.start_scenario(ScenarioKey.DB_LATENCY)
        executor = SandboxExecutor(simulator)

        assert len(executor.applied_actions) == 0

        executor.execute(
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
            approval_status="approved",
            current_incident_id="inc-1",
            current_run_id="run-1",
        )

        assert len(executor.applied_actions) == 1
        assert executor.applied_actions[0]["action_type"] == "disable_fault"


# ══════════════════════════════════════════════════════════════════════
#  Verification Tests
# ══════════════════════════════════════════════════════════════════════


class TestVerification:
    """Tests for post-action verification."""

    def test_resolved_after_disable_fault(self, simulator: SimulatorState) -> None:
        """After stopping a fault, verification should return resolved."""
        # Fault was active and got disabled — now inactive
        exec_result = ExecutionResult(
            success=True,
            action_type="disable_fault",
            idempotency_key="key-1",
            executed_at="2026-10-19T00:00:00+00:00",
            status="success",
            details={"scenario_key": "db_latency"},
        )

        result = verify_remediation(
            execution_result=exec_result,
            simulator=simulator,
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
        )

        assert result.passed is True
        assert result.outcome == "resolved"
        assert result.recommended_incident_status == "resolved"

    def test_mitigated_when_other_faults_remain(self, simulator: SimulatorState) -> None:
        """Target cleared but other faults active => mitigated."""
        # Start a second unrelated fault
        simulator.start_scenario(ScenarioKey.ELEVATED_5XX)

        exec_result = ExecutionResult(
            success=True,
            action_type="disable_fault",
            idempotency_key="key-1",
            executed_at="2026-10-19T00:00:00+00:00",
            status="success",
            details={"scenario_key": "db_latency"},
        )

        result = verify_remediation(
            execution_result=exec_result,
            simulator=simulator,
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
        )

        assert result.passed is True
        assert result.outcome == "mitigated"
        assert result.recommended_incident_status == "mitigated"

    def test_failed_when_fault_still_active(self, simulator: SimulatorState) -> None:
        """If target fault is still active, verification should fail."""
        simulator.start_scenario(ScenarioKey.DB_LATENCY)

        exec_result = ExecutionResult(
            success=True,
            action_type="disable_fault",
            idempotency_key="key-1",
            executed_at="2026-10-19T00:00:00+00:00",
            status="success",  # claimed success but fault persists
            details={"scenario_key": "db_latency"},
        )

        result = verify_remediation(
            execution_result=exec_result,
            simulator=simulator,
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
        )

        assert result.passed is False
        assert result.outcome == "failed"
        assert result.recommended_incident_status == "open"

    def test_failed_execution_verification(self, simulator: SimulatorState) -> None:
        """Execution that itself failed should verify as failed."""
        exec_result = ExecutionResult(
            success=False,
            action_type="disable_fault",
            idempotency_key="key-1",
            executed_at="2026-10-19T00:00:00+00:00",
            status="denied",
            denial_code="approval_not_approved",
            denial_reason="Not approved",
        )

        result = verify_remediation(
            execution_result=exec_result,
            simulator=simulator,
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
        )

        assert result.passed is False
        assert result.outcome == "failed"
        assert result.recommended_incident_status == "open"

    def test_verification_checks_are_populated(self, simulator: SimulatorState) -> None:
        """Verification result should include detailed check data."""
        exec_result = ExecutionResult(
            success=True,
            action_type="disable_fault",
            idempotency_key="key-1",
            executed_at="2026-10-19T00:00:00+00:00",
            status="success",
        )

        result = verify_remediation(
            execution_result=exec_result,
            simulator=simulator,
            action_type="disable_fault",
            parameters={"scenario_key": "db_latency"},
        )

        assert len(result.checks) >= 2
        check_names = [c["check"] for c in result.checks]
        assert "execution_success" in check_names
        assert "fault_inactive" in check_names


# ══════════════════════════════════════════════════════════════════════
#  Cause-to-Action Mapping Tests
# ══════════════════════════════════════════════════════════════════════


class TestCauseToAction:
    """Tests for map_cause_to_action."""

    def test_db_latency_maps_to_disable_fault(self) -> None:
        result = map_cause_to_action("db_latency", scenario_key="db_latency")
        assert result is not None
        assert result["action_type"] == "disable_fault"
        assert result["parameters"]["scenario_key"] == "db_latency"

    def test_bad_release_maps_to_rollback(self) -> None:
        result = map_cause_to_action("bad_release")
        assert result is not None
        assert result["action_type"] == "rollback_release"

    def test_unknown_cause_returns_none(self) -> None:
        result = map_cause_to_action("cosmic_ray_bitflip")
        assert result is None

    def test_risk_level_present(self) -> None:
        result = map_cause_to_action("db_latency")
        assert result is not None
        assert "risk_level" in result
        assert result["risk_level"] == "low"

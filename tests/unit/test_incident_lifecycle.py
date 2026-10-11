"""Unit tests for the incident lifecycle service."""

from __future__ import annotations

from app.incidents.service import (
    ALLOWED_TRANSITIONS,
    RUN_TRANSITIONS,
)


class TestAllowedTransitions:
    """Verify the incident status transition map is consistent."""

    def test_all_statuses_have_entries(self) -> None:
        expected = {
            "open",
            "investigating",
            "awaiting_approval",
            "remediating",
            "verifying",
            "resolved",
            "mitigated",
        }
        assert set(ALLOWED_TRANSITIONS.keys()) == expected

    def test_open_can_go_to_investigating(self) -> None:
        assert "investigating" in ALLOWED_TRANSITIONS["open"]

    def test_open_can_be_resolved_directly(self) -> None:
        assert "resolved" in ALLOWED_TRANSITIONS["open"]

    def test_resolved_can_be_reopened(self) -> None:
        assert "open" in ALLOWED_TRANSITIONS["resolved"]

    def test_investigating_can_reach_awaiting_approval(self) -> None:
        assert "awaiting_approval" in ALLOWED_TRANSITIONS["investigating"]

    def test_awaiting_approval_can_go_to_remediating(self) -> None:
        assert "remediating" in ALLOWED_TRANSITIONS["awaiting_approval"]

    def test_verifying_can_resolve_or_mitigate(self) -> None:
        assert "resolved" in ALLOWED_TRANSITIONS["verifying"]
        assert "mitigated" in ALLOWED_TRANSITIONS["verifying"]

    def test_no_self_transitions(self) -> None:
        """No status should be able to transition to itself."""
        for status, targets in ALLOWED_TRANSITIONS.items():
            assert status not in targets, f"Self-transition found for '{status}'"


class TestRunTransitions:
    """Verify the run status transition map."""

    def test_all_run_statuses_have_entries(self) -> None:
        expected = {
            "pending",
            "running",
            "awaiting_approval",
            "completed",
            "failed",
            "cancelled",
        }
        assert set(RUN_TRANSITIONS.keys()) == expected

    def test_terminal_states_have_no_transitions(self) -> None:
        assert RUN_TRANSITIONS["completed"] == set()
        assert RUN_TRANSITIONS["failed"] == set()
        assert RUN_TRANSITIONS["cancelled"] == set()

    def test_pending_can_start_or_cancel(self) -> None:
        assert "running" in RUN_TRANSITIONS["pending"]
        assert "cancelled" in RUN_TRANSITIONS["pending"]

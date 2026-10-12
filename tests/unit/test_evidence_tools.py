"""Unit tests for the evidence tools validation logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.incidents.evidence_tools import (
    DEFAULT_LIMIT,
    MAX_RESULTS,
    MAX_WINDOW_HOURS,
    ToolResult,
    _validate_window,
)


class TestValidateWindow:
    """Verify the shared validation guard for evidence tools."""

    def test_valid_window_passes(self) -> None:
        now = datetime.now(UTC)
        result = _validate_window("shopapi", now - timedelta(hours=1), now, DEFAULT_LIMIT)
        assert result is None

    def test_invalid_service_rejected(self) -> None:
        now = datetime.now(UTC)
        result = _validate_window("unknown_service", now - timedelta(hours=1), now, DEFAULT_LIMIT)
        assert result is not None
        assert not result.ok
        assert result.error_code == "invalid_service"

    def test_end_before_start_rejected(self) -> None:
        now = datetime.now(UTC)
        result = _validate_window("shopapi", now, now - timedelta(hours=1), DEFAULT_LIMIT)
        assert result is not None
        assert result.error_code == "invalid_window"

    def test_window_too_large_rejected(self) -> None:
        now = datetime.now(UTC)
        result = _validate_window(
            "shopapi",
            now - timedelta(hours=MAX_WINDOW_HOURS + 1),
            now,
            DEFAULT_LIMIT,
        )
        assert result is not None
        assert result.error_code == "window_too_large"

    def test_limit_zero_rejected(self) -> None:
        now = datetime.now(UTC)
        result = _validate_window("shopapi", now - timedelta(hours=1), now, 0)
        assert result is not None
        assert result.error_code == "invalid_limit"

    def test_limit_over_max_rejected(self) -> None:
        now = datetime.now(UTC)
        result = _validate_window("shopapi", now - timedelta(hours=1), now, MAX_RESULTS + 1)
        assert result is not None
        assert result.error_code == "invalid_limit"

    def test_exact_max_window_passes(self) -> None:
        now = datetime.now(UTC)
        result = _validate_window(
            "shopapi",
            now - timedelta(hours=MAX_WINDOW_HOURS),
            now,
            DEFAULT_LIMIT,
        )
        assert result is None

    def test_exact_max_limit_passes(self) -> None:
        now = datetime.now(UTC)
        result = _validate_window("shopapi", now - timedelta(hours=1), now, MAX_RESULTS)
        assert result is None


class TestToolResult:
    """Verify the ToolResult dataclass."""

    def test_success_result(self) -> None:
        result = ToolResult(ok=True, data=[{"key": "value"}], count=1)
        assert result.ok
        assert result.count == 1
        assert result.error_code is None

    def test_error_result(self) -> None:
        result = ToolResult(
            ok=False,
            error_code="test_error",
            error_message="something failed",
        )
        assert not result.ok
        assert result.error_code == "test_error"
        assert result.data == []
        assert result.count == 0

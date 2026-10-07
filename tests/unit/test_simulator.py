"""Unit tests for the fault simulator."""

from __future__ import annotations

import time

import pytest

from app.core.settings import Settings
from app.shopapi.simulator import (
    SCENARIO_CATALOGUE,
    ActiveFault,
    ScenarioKey,
    SimulatorState,
)


def _dev_settings(**overrides: object) -> Settings:
    """Create development settings for testing."""
    defaults = {
        "app_env": "development",
        "simulator_enabled": True,
        "simulator_max_fault_seconds": 300,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestScenarioCatalogue:
    """Verify built-in scenario definitions."""

    def test_all_five_scenarios_defined(self) -> None:
        assert len(SCENARIO_CATALOGUE) == 5

    def test_all_keys_have_definitions(self) -> None:
        for key in ScenarioKey:
            assert key in SCENARIO_CATALOGUE
            defn = SCENARIO_CATALOGUE[key]
            assert defn.title
            assert defn.description
            assert defn.severity in ("critical", "high", "medium")
            assert defn.expected_root_cause
            assert len(defn.expected_evidence) > 0
            assert defn.allowed_fix
            assert defn.default_ttl_seconds > 0


class TestSimulatorState:
    """Verify simulator lifecycle operations."""

    def test_start_and_stop_scenario(self) -> None:
        sim = SimulatorState(_dev_settings())
        fault = sim.start_scenario(ScenarioKey.DB_LATENCY)

        assert isinstance(fault, ActiveFault)
        assert fault.scenario_key == ScenarioKey.DB_LATENCY
        assert sim.is_fault_active(ScenarioKey.DB_LATENCY)

        sim.stop_scenario(ScenarioKey.DB_LATENCY)
        assert not sim.is_fault_active(ScenarioKey.DB_LATENCY)

    def test_cannot_start_same_scenario_twice(self) -> None:
        sim = SimulatorState(_dev_settings())
        sim.start_scenario(ScenarioKey.ELEVATED_5XX)

        with pytest.raises(ValueError, match="already active"):
            sim.start_scenario(ScenarioKey.ELEVATED_5XX)

    def test_cannot_stop_inactive_scenario(self) -> None:
        sim = SimulatorState(_dev_settings())
        with pytest.raises(ValueError, match="not active"):
            sim.stop_scenario(ScenarioKey.DB_LATENCY)

    def test_simulator_disabled_rejects_start(self) -> None:
        sim = SimulatorState(_dev_settings(simulator_enabled=False))
        with pytest.raises(ValueError, match="disabled"):
            sim.start_scenario(ScenarioKey.DB_LATENCY)

    def test_non_development_rejects_start(self) -> None:
        sim = SimulatorState(_dev_settings(app_env="production"))
        with pytest.raises(ValueError, match="development"):
            sim.start_scenario(ScenarioKey.DB_LATENCY)

    def test_ttl_capped_by_settings(self) -> None:
        sim = SimulatorState(_dev_settings(simulator_max_fault_seconds=30))
        fault = sim.start_scenario(ScenarioKey.DB_LATENCY)
        # DB_LATENCY default TTL is 120s, but settings cap it to 30
        assert fault.ttl_seconds == 30

    def test_get_fault_parameter(self) -> None:
        sim = SimulatorState(_dev_settings())
        sim.start_scenario(ScenarioKey.DB_LATENCY)

        delay = sim.get_fault_parameter(ScenarioKey.DB_LATENCY, "delay_ms")
        assert delay == 900

        missing = sim.get_fault_parameter(ScenarioKey.DB_LATENCY, "nonexistent", 42)
        assert missing == 42

    def test_get_fault_parameter_inactive(self) -> None:
        sim = SimulatorState(_dev_settings())
        val = sim.get_fault_parameter(ScenarioKey.DB_LATENCY, "delay_ms")
        assert val is None

    def test_stop_all(self) -> None:
        sim = SimulatorState(_dev_settings())
        sim.start_scenario(ScenarioKey.DB_LATENCY)
        sim.start_scenario(ScenarioKey.ELEVATED_5XX)
        assert len(sim.active_faults) == 2

        count = sim.stop_all()
        assert count == 2
        assert len(sim.active_faults) == 0

    def test_multiple_scenarios_can_coexist(self) -> None:
        sim = SimulatorState(_dev_settings())
        sim.start_scenario(ScenarioKey.DB_LATENCY)
        sim.start_scenario(ScenarioKey.ELEVATED_5XX)
        sim.start_scenario(ScenarioKey.DEPENDENCY_TIMEOUT)

        assert sim.is_fault_active(ScenarioKey.DB_LATENCY)
        assert sim.is_fault_active(ScenarioKey.ELEVATED_5XX)
        assert sim.is_fault_active(ScenarioKey.DEPENDENCY_TIMEOUT)

    def test_bad_release_records_change_history(self) -> None:
        sim = SimulatorState(_dev_settings())
        sim.start_scenario(ScenarioKey.BAD_RELEASE)

        history = sim.change_history
        assert len(history) == 1
        assert history[0]["type"] == "deployment"
        assert history[0]["service"] == "shopapi"
        assert "v2.1.0-buggy" in history[0]["version"]


class TestActiveFault:
    """Verify ActiveFault properties."""

    def test_remaining_seconds_decreases(self) -> None:
        fault = ActiveFault(
            scenario_key=ScenarioKey.DB_LATENCY,
            started_at=time.monotonic() - 10,
            started_at_utc="2026-01-01T00:00:00Z",
            ttl_seconds=120,
            parameters={"delay_ms": 900},
        )
        assert fault.remaining_seconds <= 110
        assert not fault.is_expired

    def test_expired_fault(self) -> None:
        fault = ActiveFault(
            scenario_key=ScenarioKey.DB_LATENCY,
            started_at=time.monotonic() - 200,
            started_at_utc="2026-01-01T00:00:00Z",
            ttl_seconds=120,
            parameters={},
        )
        assert fault.is_expired
        assert fault.remaining_seconds == 0.0

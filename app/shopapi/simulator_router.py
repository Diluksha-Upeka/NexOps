"""Simulator control API — start, stop, and inspect fault scenarios.

These endpoints are only available in development mode when the
simulator is enabled.  Every action is logged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.shopapi.simulator import (
    SCENARIO_CATALOGUE,
    ScenarioKey,
    get_simulator,
)

router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])


@router.get("/scenarios")
async def list_scenarios() -> list[dict[str, Any]]:
    """List all available scenarios and their active/inactive status."""
    simulator = get_simulator()
    active = simulator.active_faults
    result = []
    for key, defn in SCENARIO_CATALOGUE.items():
        fault = active.get(key)
        result.append(
            {
                "key": key.value,
                "title": defn.title,
                "description": defn.description,
                "severity": defn.severity,
                "default_ttl_seconds": defn.default_ttl_seconds,
                "active": fault is not None,
                "remaining_seconds": round(fault.remaining_seconds, 1) if fault else None,
                "parameters": dict(defn.parameters),
                "simulated": True,
            }
        )
    return result


@router.post("/scenarios/{scenario_key}/start")
async def start_scenario(scenario_key: str) -> dict[str, Any]:
    """Start a fault scenario."""
    try:
        key = ScenarioKey(scenario_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scenario: {scenario_key!r}. "
            f"Available: {[k.value for k in ScenarioKey]}",
        ) from exc

    simulator = get_simulator()
    try:
        fault = simulator.start_scenario(key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    defn = SCENARIO_CATALOGUE[key]
    return {
        "status": "started",
        "scenario": key.value,
        "title": defn.title,
        "severity": defn.severity,
        "ttl_seconds": fault.ttl_seconds,
        "parameters": fault.parameters,
        "started_at": fault.started_at_utc,
        "simulated": True,
    }


@router.post("/scenarios/{scenario_key}/stop")
async def stop_scenario(scenario_key: str) -> dict[str, Any]:
    """Stop an active fault scenario."""
    try:
        key = ScenarioKey(scenario_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scenario: {scenario_key!r}",
        ) from exc

    simulator = get_simulator()
    try:
        simulator.stop_scenario(key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "status": "stopped",
        "scenario": key.value,
        "simulated": True,
    }


@router.get("/status")
async def simulator_status() -> dict[str, Any]:
    """Current simulator state — active faults and summary."""
    simulator = get_simulator()
    active = simulator.active_faults
    return {
        "active_fault_count": len(active),
        "active_faults": [
            {
                "scenario": k.value,
                "started_at": f.started_at_utc,
                "remaining_seconds": round(f.remaining_seconds, 1),
                "parameters": f.parameters,
            }
            for k, f in active.items()
        ],
        "change_history": simulator.change_history,
        "simulated": True,
    }


@router.get("/telemetry")
async def simulator_telemetry_summary() -> dict[str, Any]:
    """Brief summary of demo telemetry (full queries in Phase 2)."""
    simulator = get_simulator()
    active = simulator.active_faults
    return {
        "hint": "Full telemetry query tools arrive in Phase 2. "
        "For now, use the /docs Swagger UI to exercise ShopAPI endpoints "
        "and watch structured logs on the server console.",
        "active_scenarios": [k.value for k in active],
        "simulated": True,
    }

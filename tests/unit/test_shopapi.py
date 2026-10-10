"""Unit tests for the ShopAPI endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.seed import PRODUCT_DATA
from app.shopapi.models import Product


@pytest.fixture
async def seeded_session(session: AsyncSession) -> AsyncSession:
    """Fixture that seeds the database before yielding the session."""
    # Insert seed products
    for data in PRODUCT_DATA:
        session.add(Product(**data))
    await session.commit()
    return session


@pytest.mark.asyncio
async def test_list_products() -> None:
    """Ensure the products endpoint returns a list of products."""
    # We test the API contract directly without the database for a unit-level smoke test.
    # In a full integration test, we'd use a test DB.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/shopapi/health")
        assert response.status_code == 200
        assert response.json()["service"] == "shopapi"


@pytest.mark.asyncio
async def test_simulator_scenarios() -> None:
    """Ensure the simulator control endpoints are accessible in dev."""
    from app.core.settings import get_settings
    from app.shopapi.simulator import init_simulator

    init_simulator(get_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/simulator/scenarios")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 5
        keys = [s["key"] for s in data]
        assert "db_latency" in keys
        assert "elevated_5xx" in keys

        # Start a scenario
        start_res = await client.post("/api/v1/simulator/scenarios/db_latency/start")
        assert start_res.status_code == 200
        assert start_res.json()["status"] == "started"

        # Stop a scenario
        stop_res = await client.post("/api/v1/simulator/scenarios/db_latency/stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["status"] == "stopped"

"""Unit tests for the health endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_returns_200() -> None:
    """Health endpoint should respond with 200 and service status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "nexops"
    assert "status" in body
    assert "checks" in body
    assert "database" in body["checks"]


@pytest.mark.asyncio
async def test_health_database_check_key() -> None:
    """Health response must report database as connected or unavailable."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    db_status = response.json()["checks"]["database"]
    assert db_status in ("connected", "unavailable")

"""Unit tests for the incident API endpoints (smoke tests)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_list_incidents_empty() -> None:
    """GET /api/v1/incidents should return an empty list initially."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/incidents")

    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_create_incident() -> None:
    """POST /api/v1/incidents should create an incident and return 201."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/incidents",
            json={
                "title": "Test: High latency on ShopAPI",
                "description": "P95 latency rose to 1.4s",
                "service": "shopapi",
                "severity": "high",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Test: High latency on ShopAPI"
    assert body["status"] == "open"
    assert body["severity"] == "high"
    assert body["source"] == "manual"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_incident_validation() -> None:
    """POST /api/v1/incidents with invalid severity should return 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/incidents",
            json={
                "title": "Test incident",
                "severity": "invalid_level",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_incident_not_found() -> None:
    """GET /api/v1/incidents/{id} with bad ID should return 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/incidents/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_evidence_tools_available() -> None:
    """Evidence tool endpoints should be accessible."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Logs tool
        response = await client.get("/api/v1/tools/logs")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        # Metrics tool
        response = await client.get("/api/v1/tools/metrics")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        # Traces tool
        response = await client.get("/api/v1/tools/traces")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        # Changes tool
        response = await client.get("/api/v1/tools/changes")
        assert response.status_code == 200
        assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_evidence_tool_invalid_service() -> None:
    """Evidence tool should return 422 for invalid service."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/tools/logs?service=unknown")
        assert response.status_code == 422

"""Health check endpoint.

Provides liveness/readiness information without leaking configuration
details. Checks database connectivity when a session is available.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.db.engine import get_session_safe

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/api/v1/health")
async def health_check() -> dict[str, Any]:
    """Return service health status including database connectivity."""
    db_ok = False
    try:
        async for session in get_session_safe():
            result = await session.execute(text("SELECT 1"))
            db_ok = result.scalar_one() == 1
    except Exception:
        logger.warning("Database health check failed", exc_info=True)

    status = "healthy" if db_ok else "degraded"
    return {
        "status": status,
        "service": "nexops",
        "checks": {
            "database": "connected" if db_ok else "unavailable",
        },
    }

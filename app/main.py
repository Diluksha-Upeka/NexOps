"""FastAPI application assembly.

This is the single entry point for the API server. It wires together
settings, logging, database lifecycle, CORS, and all routers.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# Windows: psycopg requires SelectorEventLoop, not ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.core.logging import setup_logging
from app.core.settings import get_settings
from app.db.engine import dispose_engine, init_engine
from app.shopapi.router import router as shopapi_router
from app.shopapi.simulator import init_simulator
from app.shopapi.simulator_router import router as simulator_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycle."""
    settings = get_settings()

    # Logging
    setup_logging(level=settings.log_level)
    logger.info(
        "Starting NexOps API",
        extra={
            "structured": {
                "env": settings.app_env,
                "host": settings.app_host,
                "port": settings.app_port,
            }
        },
    )

    # Database
    init_engine(settings)
    logger.info("Database engine initialised")

    # Simulator
    init_simulator(settings)
    logger.info(
        "Fault simulator initialised",
        extra={
            "structured": {
                "enabled": settings.simulator_enabled,
                "max_fault_seconds": settings.simulator_max_fault_seconds,
            }
        },
    )

    yield

    # Shutdown
    await dispose_engine()
    logger.info("Database engine disposed — shutdown complete")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="NexOps",
        summary="Agentic Incident Response System",
        description=(
            "A local incident-response workbench that investigates simulated service "
            "incidents using a LangGraph workflow with human-in-the-loop approval."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS — allow the local frontend origin only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health_router)
    app.include_router(shopapi_router)

    # Simulator routes — only in development
    if settings.simulator_enabled and settings.is_development:
        app.include_router(simulator_router)

    return app


# Uvicorn entry point: `uvicorn app.main:app --reload`
app = create_app()

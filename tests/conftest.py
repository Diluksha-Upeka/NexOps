"""Global pytest fixtures for test suite."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio

from app.core.settings import get_settings
from app.db.engine import dispose_engine, init_engine
from app.shopapi.simulator import init_simulator


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db() -> AsyncGenerator[None, None]:
    """Ensure database engine and simulator are initialised for test execution."""
    settings = get_settings()
    init_engine(settings)
    init_simulator(settings)
    yield
    await dispose_engine()

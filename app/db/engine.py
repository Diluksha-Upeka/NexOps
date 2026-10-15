"""Async SQLAlchemy engine and session factory.

Creates a single engine per process lifetime. The session factory provides
async sessions for request-scoped database work. Connection pool is sized
conservatively for local development.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings

# Module-level references set by ``init_engine``.
_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> None:
    """Create the async engine and session factory. Call once at startup."""
    global _engine, _session_factory

    _engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a scoped async session."""
    if _session_factory is None:
        raise RuntimeError("Database engine not initialised — call init_engine() first.")
    async with _session_factory() as session:
        yield session


async def get_session_safe() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session if the engine is initialised, otherwise yield nothing.

    Use this for optional DB checks (e.g. health endpoint) where the
    caller can handle the absence of a session gracefully.
    """
    if _session_factory is None:
        return
    async with _session_factory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Open an application session for work detached from an HTTP request."""
    if _session_factory is None:
        raise RuntimeError("Database engine not initialised — call init_engine() first.")
    async with _session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the engine connection pool. Call on shutdown."""
    if _engine is not None:
        await _engine.dispose()

"""Checkpointer factory and lifecycle management for LangGraph persistent workflows.

Supports:
  - AsyncPostgresSaver for durable execution, thread persistence, and crash recovery
  - MemorySaver fallback for fast deterministic tests and zero-dependency mode
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from app.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_checkpointer: BaseCheckpointSaver[Any] | None = None
_checkpointer_context: Any = None


async def init_checkpointer(
    settings: Settings | None = None,
    *,
    force_memory: bool = False,
) -> BaseCheckpointSaver[Any]:
    """Initialize the LangGraph checkpointer for the application process."""
    global _checkpointer, _checkpointer_context

    app_settings = settings or get_settings()

    # Use MemorySaver if forced (e.g. unit tests) or configured
    if force_memory or app_settings.app_env == "test":
        logger.info("Initializing in-memory graph checkpointer (MemorySaver)")
        _checkpointer = MemorySaver()
        return _checkpointer

    # Connect to PostgreSQL checkpointer
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        raw_url = app_settings.database_url
        # Clean psycopg scheme for standard libpq connection
        conn_str = raw_url.replace("postgresql+psycopg://", "postgresql://")

        # AsyncPostgresSaver.from_conn_string manages connection pooling
        context = AsyncPostgresSaver.from_conn_string(conn_str)
        saver = await context.__aenter__()
        await saver.setup()

        _checkpointer = saver
        _checkpointer_context = context
        logger.info("Initialized PostgreSQL graph checkpointer (AsyncPostgresSaver)")
        return _checkpointer
    except Exception as exc:
        logger.warning(
            "Failed to initialize PostgreSQL checkpointer: %s. Falling back to MemorySaver.",
            exc,
        )
        _checkpointer = MemorySaver()
        return _checkpointer


def get_checkpointer() -> BaseCheckpointSaver[Any]:
    """Return the active checkpointer, defaulting to MemorySaver if uninitialized."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
    return _checkpointer


async def close_checkpointer() -> None:
    """Dispose checkpointer connection pool during application shutdown."""
    global _checkpointer, _checkpointer_context
    if _checkpointer_context is not None:
        try:
            await _checkpointer_context.__aexit__(None, None, None)
            logger.info("Disposed PostgreSQL graph checkpointer")
        except Exception as exc:
            logger.warning("Error disposing checkpointer: %s", exc)
        finally:
            _checkpointer_context = None
            _checkpointer = None

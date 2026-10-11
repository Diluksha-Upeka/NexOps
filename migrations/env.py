"""Alembic environment configuration.

Uses the application's Settings to resolve the database URL so there
is a single source of truth for the connection string. Supports both
online (connected) and offline (SQL-script) migrations.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.settings import get_settings

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Set up Python logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import models so their tables are registered on Base.metadata
from app.db.base import Base  # noqa: E402
from app.incidents.models import (  # noqa: E402, F401
    AuditEvent,
    EvidenceItem,
    Incident,
    InvestigationRun,
)
from app.shopapi.models import Order, OrderItem, Product  # noqa: E402, F401
from app.shopapi.telemetry_models import TelemetryEvent  # noqa: E402, F401

target_metadata = Base.metadata

# Override the URL from application settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL without connecting."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connect and apply."""
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url", ""),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

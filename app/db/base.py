"""Declarative base for all SQLAlchemy domain models.

Every table model inherits from ``Base``. Alembic's ``env.py`` imports
``Base.metadata`` so that ``--autogenerate`` can detect schema changes.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared base class — provides metadata for migrations."""

    pass

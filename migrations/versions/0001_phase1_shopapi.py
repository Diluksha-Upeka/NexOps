"""Phase 1: ShopAPI tables — products, orders, order_items, telemetry_events.

Revision ID: 0001_phase1_shopapi
Revises: (initial)
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_phase1_shopapi"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Products ---
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(100), nullable=False, server_default="general"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # --- Orders ---
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), unique=True, nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # --- Order Items ---
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
    )

    # --- Telemetry Events ---
    op.create_table(
        "telemetry_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_id", sa.String(100), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service", sa.String(100), nullable=False, server_default="shopapi"),
        sa.Column("route", sa.String(200), nullable=True),
        sa.Column("method", sa.String(10), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("level", sa.String(20), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("span_id", sa.String(32), nullable=True),
        sa.Column("parent_span_id", sa.String(32), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
    )

    # --- Indexes ---
    op.create_index("ix_telemetry_service_time", "telemetry_events", ["service", "timestamp"])
    op.create_index("ix_telemetry_kind_time", "telemetry_events", ["kind", "timestamp"])
    op.create_index("ix_telemetry_scenario", "telemetry_events", ["scenario_id"])


def downgrade() -> None:
    op.drop_index("ix_telemetry_scenario", table_name="telemetry_events")
    op.drop_index("ix_telemetry_kind_time", table_name="telemetry_events")
    op.drop_index("ix_telemetry_service_time", table_name="telemetry_events")
    op.drop_table("telemetry_events")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("products")

"""Phase 5: Approvals table for human-in-the-loop remediation.

Revision ID: 0003_phase5_approvals
Revises: 0002_phase2_incidents
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_phase5_approvals"
down_revision = "0002_phase2_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("action_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("risk", sa.String(50), nullable=False, server_default="low"),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor", sa.String(100), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approvals_run_status", "approvals", ["run_id", "status"])
    op.create_index("ix_approvals_incident", "approvals", ["incident_id"])
    op.create_index("ix_approvals_idempotency", "approvals", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_approvals_idempotency", table_name="approvals")
    op.drop_index("ix_approvals_incident", table_name="approvals")
    op.drop_index("ix_approvals_run_status", table_name="approvals")
    op.drop_table("approvals")

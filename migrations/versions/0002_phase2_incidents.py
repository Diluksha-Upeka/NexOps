"""Phase 2: Incident domain tables — incidents, investigation_runs,
evidence_items, audit_events.

Revision ID: 0002_phase2_incidents
Revises: 0001_phase1_shopapi
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_phase2_incidents"
down_revision = "0001_phase1_shopapi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Incidents ---
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("service", sa.String(100), nullable=False, server_default="shopapi"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("scenario_key", sa.String(100), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_incidents_status_time", "incidents", ["status", "created_at"])

    # --- Investigation Runs ---
    op.create_table(
        "investigation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("graph_version", sa.String(50), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_runs_incident", "investigation_runs", ["incident_id"])

    # --- Evidence Items ---
    op.create_table(
        "evidence_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("source_ref", sa.String(500), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_evidence_run_type", "evidence_items", ["run_id", "source_type"])

    # --- Audit Events ---
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor", sa.String(100), nullable=False, server_default="system"),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_resource", "audit_events", ["resource_type", "resource_id"])
    op.create_index("ix_audit_time", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_time", table_name="audit_events")
    op.drop_index("ix_audit_resource", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_evidence_run_type", table_name="evidence_items")
    op.drop_table("evidence_items")
    op.drop_index("ix_runs_incident", table_name="investigation_runs")
    op.drop_table("investigation_runs")
    op.drop_index("ix_incidents_status_time", table_name="incidents")
    op.drop_table("incidents")

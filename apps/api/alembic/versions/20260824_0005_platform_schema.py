"""add platform audit and quality gate schema

Revision ID: 20260824_0005
Revises: 20260824_0004
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0005"
down_revision: str | None = "20260824_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def uuid_type() -> sa.Uuid:
    return sa.Uuid(as_uuid=True).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def upgrade() -> None:
    op.create_table(
        "quality_gate_runs",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", uuid_type(), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("config", json_type(), nullable=False),
        sa.Column("dimensions", json_type(), nullable=False),
        sa.Column("reasons", json_type(), nullable=False),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("version_id", uuid_type(), sa.ForeignKey("workflow_versions.id"), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_events_workflow_created", "audit_events", ["workflow_id", "created_at"])
    op.create_index("ix_audit_events_type_created", "audit_events", ["event_type", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_type_created", table_name="audit_events")
    op.drop_index("ix_audit_events_workflow_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("quality_gate_runs")

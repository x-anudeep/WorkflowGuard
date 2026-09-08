"""workflow attachments

Revision ID: 20260902_0009
Revises: 20260901_0008
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260902_0009"
down_revision = "20260901_0008"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "workflow_attachments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflow_versions.id"), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="other"),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("extracted_json", JSON_TYPE, nullable=False),
        sa.Column("clause_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_workflow_attachments_workflow", "workflow_attachments", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_attachments_workflow", table_name="workflow_attachments")
    op.drop_table("workflow_attachments")

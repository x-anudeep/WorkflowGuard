"""add workflow testing schema

Revision ID: 20260824_0003
Revises: 20260824_0002
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0003"
down_revision: str | None = "20260824_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def uuid_type() -> sa.Uuid:
    return sa.Uuid(as_uuid=True).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workflow_tests",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", uuid_type(), sa.ForeignKey("workflow_versions.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(length=50), nullable=False),
        sa.Column("input_data", json_type(), nullable=False),
        sa.Column("mocked_integrations", json_type(), nullable=False),
        sa.Column("failure_injections", json_type(), nullable=False),
        sa.Column("expected_path", json_type(), nullable=False),
        sa.Column("expected_outputs", json_type(), nullable=False),
        sa.Column("expected_side_effects", json_type(), nullable=False),
        sa.Column("forbidden_side_effects", json_type(), nullable=False),
        sa.Column("assertions", json_type(), nullable=False),
        sa.Column("expected_error", sa.Text(), nullable=True),
        sa.Column("tags", json_type(), nullable=False),
        sa.Column("importance", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("linked_requirement_id", sa.String(length=255), nullable=True),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "workflow_test_runs",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", uuid_type(), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("test_id", uuid_type(), sa.ForeignKey("workflow_tests.id"), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("execution_trace", json_type(), nullable=False),
        sa.Column("assertion_results", json_type(), nullable=False),
        sa.Column("failures", json_type(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("coverage", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workflow_test_runs")
    op.drop_table("workflow_tests")

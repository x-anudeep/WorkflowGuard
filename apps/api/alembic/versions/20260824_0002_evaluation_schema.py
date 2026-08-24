"""add semantic evaluation schema

Revision ID: 20260824_0002
Revises: 20260824_0001
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260824_0002"
down_revision: str | None = "20260824_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "requirement_specifications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("source_prompt", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("spec_json", json_type(), nullable=False),
        sa.Column("model_provider", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column(
            "requirement_spec_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("requirement_specifications.id"),
            nullable=True,
        ),
        sa.Column("validation_run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("validation_runs.id"), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("structural_score", sa.Float(), nullable=False),
        sa.Column("evaluator_version", sa.String(length=100), nullable=False),
        sa.Column("ai_provider", sa.String(length=100), nullable=True),
        sa.Column("ai_model", sa.String(length=255), nullable=True),
        sa.Column("ai_metadata", json_type(), nullable=False),
        sa.Column("limitations", json_type(), nullable=False),
        sa.Column("requirement_matches", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "evaluation_findings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("evaluation_run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("dimension", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("found", sa.Text(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=True),
        sa.Column("edge_id", sa.String(length=512), nullable=True),
        sa.Column("path", json_type(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("metadata", json_type(), nullable=False),
    )
    op.create_table(
        "dimension_scores",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("evaluation_run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("dimension", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("calculation", json_type(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dimension_scores")
    op.drop_table("evaluation_findings")
    op.drop_table("evaluation_runs")
    op.drop_table("requirement_specifications")

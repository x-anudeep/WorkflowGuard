"""add cost intelligence and repair schema

Revision ID: 20260824_0004
Revises: 20260824_0003
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0004"
down_revision: str | None = "20260824_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def uuid_type() -> sa.Uuid:
    return sa.Uuid(as_uuid=True).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def upgrade() -> None:
    op.create_table(
        "pricing_catalog",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_unit_cost", sa.Float(), nullable=False),
        sa.Column("output_unit_cost", sa.Float(), nullable=False),
        sa.Column("call_unit_cost", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "cost_scenarios",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("inputs", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "cost_estimates",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", uuid_type(), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("scenario_id", uuid_type(), sa.ForeignKey("cost_scenarios.id"), nullable=True),
        sa.Column("cost_per_run", sa.Float(), nullable=False),
        sa.Column("daily_cost", sa.Float(), nullable=False),
        sa.Column("monthly_cost", sa.Float(), nullable=False),
        sa.Column("annual_cost", sa.Float(), nullable=False),
        sa.Column("scenario", json_type(), nullable=False),
        sa.Column("line_items", json_type(), nullable=False),
        sa.Column("assumptions", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "optimization_findings",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("cost_estimate_id", uuid_type(), sa.ForeignKey("cost_estimates.id"), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=True),
        sa.Column("estimated_monthly_savings", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(length=50), nullable=False),
        sa.Column("deterministic", sa.Integer(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "repair_proposals",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", uuid_type(), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("finding_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("patch", json_type(), nullable=False),
        sa.Column("preview", json_type(), nullable=False),
        sa.Column("safety_flags", json_type(), nullable=False),
        sa.Column("accepted_version_id", uuid_type(), sa.ForeignKey("workflow_versions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "repair_validation_results",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("repair_proposal_id", uuid_type(), sa.ForeignKey("repair_proposals.id"), nullable=False),
        sa.Column("result_type", sa.String(length=100), nullable=False),
        sa.Column("result", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("repair_validation_results")
    op.drop_table("repair_proposals")
    op.drop_table("optimization_findings")
    op.drop_table("cost_estimates")
    op.drop_table("cost_scenarios")
    op.drop_table("pricing_catalog")

"""add fuzz campaign schema

Revision ID: 20260901_0006
Revises: 20260824_0005
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260901_0006"
down_revision: str | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def uuid_type() -> sa.Uuid:
    return sa.Uuid(as_uuid=True).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def upgrade() -> None:
    op.create_table(
        "fuzz_runs",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", uuid_type(), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exercised_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("handled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unhandled_crash", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("silent_success", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hung", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("not_triggered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("robustness_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("generated_by", sa.String(length=50), nullable=False, server_default="SYSTEM"),
        sa.Column("ai_provider", sa.String(length=50), nullable=True),
        sa.Column("ai_model", sa.String(length=255), nullable=True),
        sa.Column("ai_metadata", json_type(), nullable=False, server_default="{}"),
        sa.Column("findings", json_type(), nullable=False, server_default="[]"),
        sa.Column("limitations", json_type(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "fuzz_cases",
        sa.Column("id", uuid_type(), primary_key=True),
        sa.Column("fuzz_run_id", uuid_type(), sa.ForeignKey("fuzz_runs.id"), nullable=False),
        sa.Column("workflow_id", uuid_type(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("verdict", sa.String(length=50), nullable=False),
        sa.Column("observed", sa.Text(), nullable=False, server_default=""),
        sa.Column("generated_by", sa.String(length=50), nullable=False, server_default="SYSTEM"),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_data", json_type(), nullable=False, server_default="{}"),
        sa.Column("failure_injections", json_type(), nullable=False, server_default="[]"),
        sa.Column("targeted_node_ids", json_type(), nullable=False, server_default="[]"),
        sa.Column("evidence", json_type(), nullable=False, server_default="[]"),
        sa.Column("execution_trace", json_type(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_fuzz_runs_workflow_created", "fuzz_runs", ["workflow_id", "created_at"])
    op.create_index("ix_fuzz_cases_run_verdict", "fuzz_cases", ["fuzz_run_id", "verdict"])


def downgrade() -> None:
    op.drop_index("ix_fuzz_cases_run_verdict", table_name="fuzz_cases")
    op.drop_index("ix_fuzz_runs_workflow_created", table_name="fuzz_runs")
    op.drop_table("fuzz_cases")
    op.drop_table("fuzz_runs")

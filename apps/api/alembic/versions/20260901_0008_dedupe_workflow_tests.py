"""remove duplicate generated workflow tests

Repeated presses of "Generate Tests" re-persisted the whole generated corpus, so a
workflow accumulated a fresh copy of every test on each press. This keeps the earliest
row for each (workflow, name) pair and deletes the copies, along with the test runs that
belong to the copies - those runs duplicate the kept test's history rather than
recording anything distinct.

Revision ID: 20260901_0008
Revises: 20260901_0007
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_0008"
down_revision: str | None = "20260901_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Window function rather than MIN(id): PostgreSQL has no MIN aggregate for uuid, but
#: both PostgreSQL and SQLite (3.25+) support ROW_NUMBER.
_DUPLICATE_TEST_IDS = """
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (
            PARTITION BY workflow_id, name ORDER BY created_at, id
        ) AS row_number
        FROM workflow_tests
    ) ranked
    WHERE ranked.row_number > 1
"""


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(f"DELETE FROM workflow_test_runs WHERE test_id IN ({_DUPLICATE_TEST_IDS})")
    )
    connection.execute(sa.text(f"DELETE FROM workflow_tests WHERE id IN ({_DUPLICATE_TEST_IDS})"))


def downgrade() -> None:
    # Deleted duplicates cannot be reconstructed, and recreating them would restore the
    # bug this migration exists to undo.
    pass

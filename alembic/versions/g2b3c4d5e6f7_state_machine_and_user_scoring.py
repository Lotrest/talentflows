"""state machine fields and user scoring settings

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-04-25 01:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "g2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Vacancy state machine extras
    op.add_column("vacancies", sa.Column("apply_error", sa.String(), nullable=True))
    op.add_column("vacancies", sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True))

    # User scoring & apply controls
    op.add_column("users", sa.Column("score_threshold", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("users", sa.Column("daily_apply_limit", sa.Integer(), nullable=False, server_default="20"))
    op.add_column("users", sa.Column("target_role", sa.String(), nullable=True))
    op.add_column("users", sa.Column("rejected_companies", sa.JSON(), nullable=False, server_default="[]"))

    # Backfill: existing "scored" vacancies with good score → "new" so users can still see them
    op.execute("""
        UPDATE vacancies SET status = 'new'
        WHERE status = 'scored' AND score >= 60
    """)


def downgrade() -> None:
    op.drop_column("vacancies", "apply_error")
    op.drop_column("vacancies", "applied_at")
    op.drop_column("users", "score_threshold")
    op.drop_column("users", "daily_apply_limit")
    op.drop_column("users", "target_role")
    op.drop_column("users", "rejected_companies")

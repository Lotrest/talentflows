"""add vacancy status field

Revision ID: f1a2b3c4d5e6
Revises: e7f6a5b4c3d2
Create Date: 2026-04-25 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e7f6a5b4c3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vacancies", sa.Column("status", sa.String(), nullable=False, server_default="new"))

    # Backfill: applied vacancies → "applied", archived → "rejected", rest → "shown"
    op.execute("""
        UPDATE vacancies SET status = CASE
            WHEN is_applied = TRUE THEN 'applied'
            WHEN is_archived = TRUE THEN 'rejected'
            ELSE 'shown'
        END
    """)

    op.create_index("ix_vacancies_user_status", "vacancies", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_vacancies_user_status", table_name="vacancies")
    op.drop_column("vacancies", "status")

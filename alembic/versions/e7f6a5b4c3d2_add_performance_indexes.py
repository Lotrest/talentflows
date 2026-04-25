"""add performance indexes

Revision ID: e7f6a5b4c3d2
Revises: d6e5f4a3b2c1
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "e7f6a5b4c3d2"
down_revision: Union[str, None] = "d6e5f4a3b2c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_vacancies_user_id", "vacancies", ["user_id"], if_not_exists=True)
    op.create_index("ix_vacancies_user_score", "vacancies", ["user_id", "score"], if_not_exists=True)
    op.create_index("ix_vacancies_user_found_at", "vacancies", ["user_id", "found_at"], if_not_exists=True)
    op.create_index("ix_vacancies_user_archived", "vacancies", ["user_id", "is_archived"], if_not_exists=True)
    op.create_index("ix_applications_user_id", "applications", ["user_id"], if_not_exists=True)
    op.create_index("ix_applications_user_status", "applications", ["user_id", "status"], if_not_exists=True)
    op.create_index("ix_applications_user_sent_at", "applications", ["user_id", "sent_at"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_vacancies_user_id", table_name="vacancies")
    op.drop_index("ix_vacancies_user_score", table_name="vacancies")
    op.drop_index("ix_vacancies_user_found_at", table_name="vacancies")
    op.drop_index("ix_vacancies_user_archived", table_name="vacancies")
    op.drop_index("ix_applications_user_id", table_name="applications")
    op.drop_index("ix_applications_user_status", table_name="applications")
    op.drop_index("ix_applications_user_sent_at", table_name="applications")

"""add hh_resume_id to users

Revision ID: a3b2c1d4e5f6
Revises: 9efc1f1a783a
Create Date: 2026-04-22 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'a3b2c1d4e5f6'
down_revision: Union[str, None] = '9efc1f1a783a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('hh_resume_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'hh_resume_id')

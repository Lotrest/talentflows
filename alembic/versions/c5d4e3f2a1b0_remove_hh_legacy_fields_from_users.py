"""remove hh legacy fields from users

Revision ID: c5d4e3f2a1b0
Revises: b4c3d2e1f0a9
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c5d4e3f2a1b0'
down_revision: Union[str, None] = 'b4c3d2e1f0a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('users', 'hh_access_token')
    op.drop_column('users', 'hh_refresh_token')
    op.drop_column('users', 'hh_token_expires_at')
    op.drop_column('users', 'hh_resume_id')


def downgrade() -> None:
    op.add_column('users', sa.Column('hh_resume_id', sa.String(), nullable=True))
    op.add_column('users', sa.Column('hh_token_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('hh_refresh_token', sa.String(), nullable=True))
    op.add_column('users', sa.Column('hh_access_token', sa.String(), nullable=True))

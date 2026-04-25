"""add platform_connections table

Revision ID: b4c3d2e1f0a9
Revises: a3b2c1d4e5f6
Create Date: 2026-04-22 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b4c3d2e1f0a9'
down_revision: Union[str, None] = 'a3b2c1d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'platform_connections',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('access_token', sa.String(), nullable=True),
        sa.Column('refresh_token', sa.String(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('platform_user_id', sa.String(), nullable=True),
        sa.Column('platform_email', sa.String(), nullable=True),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'platform', name='uq_user_platform'),
    )
    op.create_index('ix_platform_connections_user_id', 'platform_connections', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_platform_connections_user_id', 'platform_connections')
    op.drop_table('platform_connections')

"""add subscription fields to users

Revision ID: d6e5f4a3b2c1
Revises: c5d4e3f2a1b0
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd6e5f4a3b2c1'
down_revision: Union[str, None] = 'c5d4e3f2a1b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('stripe_customer_id', sa.String(), nullable=True, unique=True))
    op.add_column('users', sa.Column('stripe_subscription_id', sa.String(), nullable=True, unique=True))
    op.add_column('users', sa.Column('subscription_status', sa.String(), nullable=False, server_default='inactive'))
    op.add_column('users', sa.Column('subscription_current_period_end', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'subscription_current_period_end')
    op.drop_column('users', 'subscription_status')
    op.drop_column('users', 'stripe_subscription_id')
    op.drop_column('users', 'stripe_customer_id')

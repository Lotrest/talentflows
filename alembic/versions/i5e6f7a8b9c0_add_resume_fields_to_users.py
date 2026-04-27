"""Add resume fields to users

Revision ID: i5e6f7a8b9c0
Revises: h4d5e6f7a8b9
Create Date: 2026-04-27

"""
from alembic import op
import sqlalchemy as sa


revision = 'i5e6f7a8b9c0'
down_revision = 'h4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('resume_filename', sa.String(), nullable=True))
    op.add_column('users', sa.Column('resume_path', sa.String(), nullable=True))
    op.add_column('users', sa.Column('resume_uploaded_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'resume_uploaded_at')
    op.drop_column('users', 'resume_path')
    op.drop_column('users', 'resume_filename')

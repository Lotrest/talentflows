"""Add email auth fields to users

Revision ID: h4d5e6f7a8b9
Revises: g2b3c4d5e6f7
Create Date: 2026-04-25

"""
from alembic import op
import sqlalchemy as sa

revision = "h4d5e6f7a8b9"
down_revision = "g2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("hashed_password", sa.String(), nullable=True))
    op.add_column("users", sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("email_code", sa.String(), nullable=True))
    op.add_column("users", sa.Column("email_code_expires", sa.DateTime(timezone=True), nullable=True))

    # OAuth users already verified via platform — mark them verified
    op.execute("""
        UPDATE users
        SET is_verified = true
        WHERE id IN (
            SELECT DISTINCT user_id FROM platform_connections
        )
    """)


def downgrade() -> None:
    op.drop_column("users", "email_code_expires")
    op.drop_column("users", "email_code")
    op.drop_column("users", "is_verified")
    op.drop_column("users", "hashed_password")

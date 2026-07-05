"""add avatar_key to users

Revision ID: 019
Revises: 018
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_key", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_key")

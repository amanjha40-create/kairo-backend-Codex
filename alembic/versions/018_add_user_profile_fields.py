"""add profile fields to users (phone, location, headline, bio, date_of_birth)

Revision ID: 018
Revises: 017
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("location", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("headline", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("bio", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "date_of_birth")
    op.drop_column("users", "bio")
    op.drop_column("users", "headline")
    op.drop_column("users", "location")
    op.drop_column("users", "phone")

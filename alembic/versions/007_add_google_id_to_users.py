"""Add google_id column to users for Google OAuth login.

Revision ID: 007_google_oauth
Revises: 006_doc_verify
Create Date: 2026-05-25

"""
from alembic import op
import sqlalchemy as sa

revision = "007_google_oauth"
down_revision = "006_doc_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("google_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_column("users", "google_id")

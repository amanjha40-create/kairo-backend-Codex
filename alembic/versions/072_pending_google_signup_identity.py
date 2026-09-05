"""Retain a validated OAuth identity until Candidate phone verification completes.

Revision ID: 072
Revises: 071
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("pending_signups", "password_hash", existing_type=sa.String(255), nullable=True)
    op.add_column("pending_signups", sa.Column("oauth_provider", sa.String(32), nullable=True))
    op.add_column("pending_signups", sa.Column("oauth_provider_user_id", sa.String(255), nullable=True))
    op.add_column("pending_signups", sa.Column("oauth_provider_email", sa.String(320), nullable=True))
    op.add_column("pending_signups", sa.Column("oauth_validated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_pending_signups_oauth_identity",
        "pending_signups",
        ["oauth_provider", "oauth_provider_user_id"],
        unique=True,
        postgresql_where=sa.text("oauth_provider_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pending_signups_oauth_identity", table_name="pending_signups")
    op.drop_column("pending_signups", "oauth_validated_at")
    op.drop_column("pending_signups", "oauth_provider_email")
    op.drop_column("pending_signups", "oauth_provider_user_id")
    op.drop_column("pending_signups", "oauth_provider")
    op.alter_column("pending_signups", "password_hash", existing_type=sa.String(255), nullable=False)

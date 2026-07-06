"""Add Trust Passport share links

Revision ID: 023
Revises: 022
Create Date: 2026-07-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passport_share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("track_views", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_passport_share_links_owner_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_passport_share_links"),
        sa.UniqueConstraint("token_hash", name="uq_passport_share_links_token_hash"),
    )
    op.create_index("ix_passport_share_links_owner_user_id", "passport_share_links", ["owner_user_id"])
    op.create_index("ix_passport_share_links_expires_at", "passport_share_links", ["expires_at"])
    op.create_index("ix_passport_share_links_revoked_at", "passport_share_links", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_passport_share_links_revoked_at", table_name="passport_share_links")
    op.drop_index("ix_passport_share_links_expires_at", table_name="passport_share_links")
    op.drop_index("ix_passport_share_links_owner_user_id", table_name="passport_share_links")
    op.drop_table("passport_share_links")

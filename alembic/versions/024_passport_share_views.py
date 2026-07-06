"""Add Trust Passport share view events

Revision ID: 024
Revises: 023
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passport_share_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("share_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("viewer_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=1024), nullable=True),
        sa.Column("referrer", sa.String(length=2048), nullable=True),
        sa.Column("is_unique_view", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["share_id"],
            ["passport_share_links.id"],
            name="fk_passport_share_views_share_id_passport_share_links",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_passport_share_views"),
    )
    op.create_index("ix_passport_share_views_share_id", "passport_share_views", ["share_id"])
    op.create_index("ix_passport_share_views_created_at", "passport_share_views", ["created_at"])
    op.create_index(
        "ix_passport_share_views_dedup",
        "passport_share_views",
        ["share_id", "viewer_ip_hash", "user_agent", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_passport_share_views_dedup", table_name="passport_share_views")
    op.drop_index("ix_passport_share_views_created_at", table_name="passport_share_views")
    op.drop_index("ix_passport_share_views_share_id", table_name="passport_share_views")
    op.drop_table("passport_share_views")

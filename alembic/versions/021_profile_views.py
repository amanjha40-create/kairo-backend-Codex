"""021 - profile view tracking

Revision ID: 021
Revises: 020
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("viewer_ip_hash", sa.String(64), nullable=False),
        sa.Column("viewer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_user_id"], ["users.id"], ondelete="CASCADE",
            name="fk_profile_views_profile_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["viewer_user_id"], ["users.id"], ondelete="SET NULL",
            name="fk_profile_views_viewer_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_profile_views"),
    )
    op.create_index("ix_profile_views_profile_user_id", "profile_views", ["profile_user_id"])
    op.create_index("ix_profile_views_viewer_user_id", "profile_views", ["viewer_user_id"])
    op.create_index("ix_profile_views_created_at", "profile_views", ["created_at"])
    # Fast dedup check: is there already a view for this IP on this profile today?
    op.create_index(
        "ix_profile_views_dedup",
        "profile_views",
        ["profile_user_id", "viewer_ip_hash", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_views_dedup", "profile_views")
    op.drop_index("ix_profile_views_created_at", "profile_views")
    op.drop_index("ix_profile_views_viewer_user_id", "profile_views")
    op.drop_index("ix_profile_views_profile_user_id", "profile_views")
    op.drop_table("profile_views")

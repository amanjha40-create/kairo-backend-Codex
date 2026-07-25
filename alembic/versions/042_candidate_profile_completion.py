"""Candidate profile location, languages, and professional links.

Revision ID: 042
Revises: 041
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("location_city", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("location_region", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("location_country", sa.String(length=2), nullable=True))
    op.create_table(
        "profile_languages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.String(length=80), nullable=False),
        sa.Column("proficiency", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "language", name="uq_profile_languages_user_language"),
    )
    op.create_index("ix_profile_languages_user_id", "profile_languages", ["user_id"])
    op.create_table(
        "profile_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_type", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "url", name="uq_profile_links_user_url"),
    )
    op.create_index("ix_profile_links_user_id", "profile_links", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_profile_links_user_id", table_name="profile_links")
    op.drop_table("profile_links")
    op.drop_index("ix_profile_languages_user_id", table_name="profile_languages")
    op.drop_table("profile_languages")
    op.drop_column("users", "location_country")
    op.drop_column("users", "location_region")
    op.drop_column("users", "location_city")

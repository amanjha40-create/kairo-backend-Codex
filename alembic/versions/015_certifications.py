"""Add certifications table.

Revision ID: 015
Revises: 014
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certifications",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("issuing_organization", sa.String(512), nullable=False),
        sa.Column("issued_date", sa.Date, nullable=False),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("does_not_expire", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("credential_id", sa.String(256), nullable=True),
        sa.Column("credential_url", sa.Text, nullable=True),
        # Optional S3 document
        sa.Column("object_key", sa.String(1024), nullable=True, unique=True),
        sa.Column("original_filename", sa.String(512), nullable=True),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("byte_size", sa.BigInteger, nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        # Verification
        sa.Column(
            "verification_status",
            sa.String(48),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps + soft-delete
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_certifications_user_id ON certifications (user_id)")


def downgrade() -> None:
    op.drop_index("ix_certifications_user_id", table_name="certifications")
    op.drop_table("certifications")

"""Add independent exact-file document packs (no Passport schema changes).

Revision ID: 078
Revises: 077
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    time = sa.DateTime(timezone=True)
    op.create_table(
        "document_share_packs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("public_id", uuid, nullable=False, unique=True),
        sa.Column(
            "owner_user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("purpose", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", time, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", time, nullable=False),
        sa.Column("revoked_at", time),
        sa.Column("view_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_viewed_at", time),
        sa.CheckConstraint("char_length(trim(purpose)) BETWEEN 1 AND 120", name="purpose_length"),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        sa.CheckConstraint("view_count >= 0", name="nonnegative_views"),
    )
    op.create_index(
        "ix_document_share_packs_owner_created",
        "document_share_packs",
        ["owner_user_id", "created_at"],
    )
    op.create_index("ix_document_share_packs_expires_at", "document_share_packs", ["expires_at"])
    op.create_table(
        "document_share_pack_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("public_id", uuid, nullable=False, unique=True),
        sa.Column(
            "pack_id",
            uuid,
            sa.ForeignKey("document_share_packs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", uuid, nullable=False),
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("context", sa.String(512)),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64)),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("object_version", sa.String(1024)),
        sa.Column("object_etag", sa.String(128), nullable=False),
        sa.Column("owns_snapshot", sa.Boolean(), nullable=False),
        sa.Column("cleaned_at", time),
        sa.Column("created_at", time, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("pack_id", "source_type", "source_id", name="uq_pack_source"),
        sa.CheckConstraint(
            "source_type IN ('vault','employment','education','certification','portfolio')",
            name="source_type",
        ),
        sa.CheckConstraint("byte_size > 0 AND byte_size <= 52428800", name="file_size"),
    )
    op.create_index(
        "ix_document_share_pack_items_pack_id", "document_share_pack_items", ["pack_id"]
    )
    op.create_index(
        "ix_document_share_pack_items_object_key", "document_share_pack_items", ["object_key"]
    )


def downgrade() -> None:
    op.drop_table("document_share_pack_items")
    op.drop_table("document_share_packs")

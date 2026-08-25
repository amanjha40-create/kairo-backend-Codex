"""Add public institution verification request persistence.

Revision ID: 071
Revises: 070
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "institution_verification_requests",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_name", sa.String(length=255), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "response_action",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("response_note", sa.Text(), nullable=True),
        sa.Column(
            "response_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["verification_request_id"],
            ["verification_requests.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "verification_request_id",
            name="uq_institution_verification_requests_verification_request_id",
        ),
        sa.UniqueConstraint("token_hash", name="uq_institution_verification_requests_token_hash"),
    )
    op.create_index(
        op.f("ix_institution_verification_requests_public_id"),
        "institution_verification_requests",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_institution_verification_requests_verification_request_id"),
        "institution_verification_requests",
        ["verification_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_verification_requests_organization_id"),
        "institution_verification_requests",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_verification_requests_recipient_email"),
        "institution_verification_requests",
        ["recipient_email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_verification_requests_token_hash"),
        "institution_verification_requests",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_verification_requests_expires_at"),
        "institution_verification_requests",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_verification_requests_revoked_at"),
        "institution_verification_requests",
        ["revoked_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_verification_requests_revoked_by_user_id"),
        "institution_verification_requests",
        ["revoked_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_institution_verification_requests_revoked_by_user_id"),
        table_name="institution_verification_requests",
    )
    op.drop_index(
        op.f("ix_institution_verification_requests_revoked_at"),
        table_name="institution_verification_requests",
    )
    op.drop_index(
        op.f("ix_institution_verification_requests_expires_at"),
        table_name="institution_verification_requests",
    )
    op.drop_index(
        op.f("ix_institution_verification_requests_token_hash"),
        table_name="institution_verification_requests",
    )
    op.drop_index(
        op.f("ix_institution_verification_requests_recipient_email"),
        table_name="institution_verification_requests",
    )
    op.drop_index(
        op.f("ix_institution_verification_requests_organization_id"),
        table_name="institution_verification_requests",
    )
    op.drop_index(
        op.f("ix_institution_verification_requests_verification_request_id"),
        table_name="institution_verification_requests",
    )
    op.drop_index(
        op.f("ix_institution_verification_requests_public_id"),
        table_name="institution_verification_requests",
    )
    op.drop_table("institution_verification_requests")

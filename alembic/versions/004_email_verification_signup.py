"""Email verification OTP signup — pending_signups + users.email_verified_at.

Revision ID: 004_email_verify
Revises: 003_onboard_relieve
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004_email_verify"
down_revision = "003_onboard_relieve"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET email_verified_at = created_at
            WHERE email_verified_at IS NULL
            """
        )
    )

    op.create_table(
        "pending_signups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("otp_sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verify_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_otp_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pending_signups")),
        sa.UniqueConstraint("email", name=op.f("uq_pending_signups_email")),
    )
    op.create_index(op.f("ix_pending_signups_email"), "pending_signups", ["email"], unique=True)
    op.create_index(op.f("ix_pending_signups_expires_at"), "pending_signups", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pending_signups_expires_at"), table_name="pending_signups")
    op.drop_index(op.f("ix_pending_signups_email"), table_name="pending_signups")
    op.drop_table("pending_signups")
    op.drop_column("users", "email_verified_at")

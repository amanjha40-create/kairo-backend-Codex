"""add dual otp signup state and quick profile fields

Revision ID: 034
Revises: 033
Create Date: 2026-07-12 17:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("current_role", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("industry", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("years_of_experience", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_users_phone", "users", ["phone"])

    op.add_column("pending_signups", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("pending_signups", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pending_signups", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "pending_signups",
        sa.Column("phone_otp_sent_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pending_signups",
        sa.Column("phone_verify_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("pending_signups", sa.Column("phone_last_otp_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pending_signups", sa.Column("completed_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("pending_signups", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_pending_signups_phone", "pending_signups", ["phone"])
    op.create_foreign_key(
        "fk_pending_signups_completed_user_id",
        "pending_signups",
        "users",
        ["completed_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_pending_signups_completed_user_id", "pending_signups", ["completed_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pending_signups_completed_user_id", table_name="pending_signups")
    op.drop_constraint("fk_pending_signups_completed_user_id", "pending_signups", type_="foreignkey")
    op.drop_constraint("uq_pending_signups_phone", "pending_signups", type_="unique")
    op.drop_column("pending_signups", "completed_at")
    op.drop_column("pending_signups", "completed_user_id")
    op.drop_column("pending_signups", "phone_last_otp_sent_at")
    op.drop_column("pending_signups", "phone_verify_attempt_count")
    op.drop_column("pending_signups", "phone_otp_sent_count")
    op.drop_column("pending_signups", "phone_verified_at")
    op.drop_column("pending_signups", "email_verified_at")
    op.drop_column("pending_signups", "phone")

    op.drop_constraint("uq_users_phone", "users", type_="unique")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "years_of_experience")
    op.drop_column("users", "industry")
    op.drop_column("users", "current_role")

"""Add email delivery audit log table.

Revision ID: 030
Revises: 029
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_delivery_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False, server_default="email.send"),
        sa.Column("template_key", sa.String(length=100), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name=op.f("fk_email_delivery_logs_recipient_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_delivery_logs")),
        sa.UniqueConstraint("public_id", name=op.f("uq_email_delivery_logs_public_id")),
    )
    op.create_index(op.f("ix_email_delivery_logs_template_key"), "email_delivery_logs", ["template_key"], unique=False)
    op.create_index(op.f("ix_email_delivery_logs_recipient_email"), "email_delivery_logs", ["recipient_email"], unique=False)
    op.create_index(op.f("ix_email_delivery_logs_recipient_user_id"), "email_delivery_logs", ["recipient_user_id"], unique=False)
    op.create_index(op.f("ix_email_delivery_logs_status"), "email_delivery_logs", ["status"], unique=False)
    op.create_index(
        "ix_email_delivery_logs_status_created_at",
        "email_delivery_logs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_delivery_logs_template_key_version_created_at",
        "email_delivery_logs",
        ["template_key", "template_version", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_delivery_logs_recipient_email_created_at",
        "email_delivery_logs",
        ["recipient_email", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_delivery_logs_recipient_user_id_created_at",
        "email_delivery_logs",
        ["recipient_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_email_delivery_logs_recipient_user_id_created_at", table_name="email_delivery_logs")
    op.drop_index("ix_email_delivery_logs_recipient_email_created_at", table_name="email_delivery_logs")
    op.drop_index("ix_email_delivery_logs_template_key_version_created_at", table_name="email_delivery_logs")
    op.drop_index("ix_email_delivery_logs_status_created_at", table_name="email_delivery_logs")
    op.drop_index(op.f("ix_email_delivery_logs_status"), table_name="email_delivery_logs")
    op.drop_index(op.f("ix_email_delivery_logs_recipient_user_id"), table_name="email_delivery_logs")
    op.drop_index(op.f("ix_email_delivery_logs_recipient_email"), table_name="email_delivery_logs")
    op.drop_index(op.f("ix_email_delivery_logs_template_key"), table_name="email_delivery_logs")
    op.drop_table("email_delivery_logs")

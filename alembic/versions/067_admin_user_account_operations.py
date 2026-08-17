"""Add admin user account operations persistence.

Revision ID: 067
Revises: 066
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("suspension_reason", sa.String(length=512), nullable=True))
    op.add_column(
        "users",
        sa.Column("suspended_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(op.f("ix_users_suspended_at"), "users", ["suspended_at"], unique=False)
    op.create_index(
        op.f("ix_users_suspended_by_user_id"),
        "users",
        ["suspended_by_user_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_users_suspended_by_user_id_users"),
        "users",
        "users",
        ["suspended_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE users
        SET suspended_at = updated_at,
            suspension_reason = COALESCE(suspension_reason, 'Backfilled legacy disabled account')
        WHERE deleted_at IS NULL
          AND is_active = FALSE
          AND suspended_at IS NULL
        """
    )

    op.create_table(
        "user_admin_notes",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("author_role", sa.String(length=32), nullable=True),
        sa.Column("author_display_name", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(op.f("ix_user_admin_notes_author_user_id"), "user_admin_notes", ["author_user_id"], unique=False)
    op.create_index(op.f("ix_user_admin_notes_user_id"), "user_admin_notes", ["user_id"], unique=False)

    op.create_table(
        "user_account_events",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("actor_display_name", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.String(length=512), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(op.f("ix_user_account_events_actor_role"), "user_account_events", ["actor_role"], unique=False)
    op.create_index(op.f("ix_user_account_events_actor_user_id"), "user_account_events", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_user_account_events_created_at"), "user_account_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_user_account_events_event_type"), "user_account_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_user_account_events_public_id"), "user_account_events", ["public_id"], unique=False)
    op.create_index(op.f("ix_user_account_events_user_id"), "user_account_events", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_account_events_user_id"), table_name="user_account_events")
    op.drop_index(op.f("ix_user_account_events_public_id"), table_name="user_account_events")
    op.drop_index(op.f("ix_user_account_events_event_type"), table_name="user_account_events")
    op.drop_index(op.f("ix_user_account_events_created_at"), table_name="user_account_events")
    op.drop_index(op.f("ix_user_account_events_actor_user_id"), table_name="user_account_events")
    op.drop_index(op.f("ix_user_account_events_actor_role"), table_name="user_account_events")
    op.drop_table("user_account_events")

    op.drop_index(op.f("ix_user_admin_notes_user_id"), table_name="user_admin_notes")
    op.drop_index(op.f("ix_user_admin_notes_author_user_id"), table_name="user_admin_notes")
    op.drop_table("user_admin_notes")

    op.drop_constraint(op.f("fk_users_suspended_by_user_id_users"), "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_suspended_by_user_id"), table_name="users")
    op.drop_index(op.f("ix_users_suspended_at"), table_name="users")
    op.drop_column("users", "suspended_by_user_id")
    op.drop_column("users", "suspension_reason")
    op.drop_column("users", "suspended_at")

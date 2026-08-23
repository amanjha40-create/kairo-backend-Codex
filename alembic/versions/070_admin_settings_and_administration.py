"""Add admin settings and administration persistence.

Revision ID: 070
Revises: 069
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_access_invitations",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invitee_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invitee_email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resend_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invitee_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("token_hash", name="uq_admin_access_invitations_token_hash"),
    )
    op.create_index(
        op.f("ix_admin_access_invitations_public_id"),
        "admin_access_invitations",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_invited_by_user_id"),
        "admin_access_invitations",
        ["invited_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_accepted_by_user_id"),
        "admin_access_invitations",
        ["accepted_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_invitee_user_id"),
        "admin_access_invitations",
        ["invitee_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_invitee_email"),
        "admin_access_invitations",
        ["invitee_email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_role"),
        "admin_access_invitations",
        ["role"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_status"),
        "admin_access_invitations",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_token_hash"),
        "admin_access_invitations",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_expires_at"),
        "admin_access_invitations",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_invitations_created_at"),
        "admin_access_invitations",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "admin_access_audit_events",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("actor_display_name", sa.String(length=255), nullable=True),
        sa.Column("subject_email", sa.String(length=320), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invitation_id"], ["admin_access_invitations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        op.f("ix_admin_access_audit_events_public_id"),
        "admin_access_audit_events",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_admin_access_audit_events_actor_user_id"),
        "admin_access_audit_events",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_audit_events_subject_user_id"),
        "admin_access_audit_events",
        ["subject_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_audit_events_invitation_id"),
        "admin_access_audit_events",
        ["invitation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_audit_events_actor_role"),
        "admin_access_audit_events",
        ["actor_role"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_audit_events_subject_email"),
        "admin_access_audit_events",
        ["subject_email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_audit_events_action"),
        "admin_access_audit_events",
        ["action"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_access_audit_events_created_at"),
        "admin_access_audit_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_access_audit_events_created_at"), table_name="admin_access_audit_events")
    op.drop_index(op.f("ix_admin_access_audit_events_action"), table_name="admin_access_audit_events")
    op.drop_index(op.f("ix_admin_access_audit_events_subject_email"), table_name="admin_access_audit_events")
    op.drop_index(op.f("ix_admin_access_audit_events_actor_role"), table_name="admin_access_audit_events")
    op.drop_index(op.f("ix_admin_access_audit_events_invitation_id"), table_name="admin_access_audit_events")
    op.drop_index(op.f("ix_admin_access_audit_events_subject_user_id"), table_name="admin_access_audit_events")
    op.drop_index(op.f("ix_admin_access_audit_events_actor_user_id"), table_name="admin_access_audit_events")
    op.drop_index(op.f("ix_admin_access_audit_events_public_id"), table_name="admin_access_audit_events")
    op.drop_table("admin_access_audit_events")

    op.drop_index(op.f("ix_admin_access_invitations_created_at"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_expires_at"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_token_hash"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_status"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_role"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_invitee_email"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_invitee_user_id"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_accepted_by_user_id"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_invited_by_user_id"), table_name="admin_access_invitations")
    op.drop_index(op.f("ix_admin_access_invitations_public_id"), table_name="admin_access_invitations")
    op.drop_table("admin_access_invitations")

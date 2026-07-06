"""Add trust invitations.

Revision ID: 027
Revises: 026
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.trust_invitations.enums import TrustInvitationStatus

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def _enum(name: str, members: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*members, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    trust_invitation_status_enum = _enum(
        "trust_invitation_status_enum",
        tuple(member.value for member in TrustInvitationStatus),
    )
    trust_invitation_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "trust_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_name", sa.String(length=255), nullable=False),
        sa.Column("subject_email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", trust_invitation_status_enum, nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_invitations_accepted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_invitations_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_trust_invitations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_invitations")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_invitations_public_id")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_trust_invitations_token_hash")),
    )
    op.create_index(op.f("ix_trust_invitations_accepted_by_user_id"), "trust_invitations", ["accepted_by_user_id"])
    op.create_index(op.f("ix_trust_invitations_created_by_user_id"), "trust_invitations", ["created_by_user_id"])
    op.create_index(op.f("ix_trust_invitations_expires_at"), "trust_invitations", ["expires_at"])
    op.create_index(op.f("ix_trust_invitations_organization_id"), "trust_invitations", ["organization_id"])
    op.create_index(op.f("ix_trust_invitations_status"), "trust_invitations", ["status"])
    op.create_index(op.f("ix_trust_invitations_subject_email"), "trust_invitations", ["subject_email"])
    op.create_index(op.f("ix_trust_invitations_token_hash"), "trust_invitations", ["token_hash"])


def downgrade() -> None:
    bind = op.get_bind()

    trust_invitation_status_enum = _enum(
        "trust_invitation_status_enum",
        tuple(member.value for member in TrustInvitationStatus),
    )

    op.drop_index(op.f("ix_trust_invitations_token_hash"), table_name="trust_invitations")
    op.drop_index(op.f("ix_trust_invitations_subject_email"), table_name="trust_invitations")
    op.drop_index(op.f("ix_trust_invitations_status"), table_name="trust_invitations")
    op.drop_index(op.f("ix_trust_invitations_organization_id"), table_name="trust_invitations")
    op.drop_index(op.f("ix_trust_invitations_expires_at"), table_name="trust_invitations")
    op.drop_index(op.f("ix_trust_invitations_created_by_user_id"), table_name="trust_invitations")
    op.drop_index(op.f("ix_trust_invitations_accepted_by_user_id"), table_name="trust_invitations")
    op.drop_table("trust_invitations")

    trust_invitation_status_enum.drop(bind, checkfirst=True)

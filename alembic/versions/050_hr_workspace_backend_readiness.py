"""HR workspace backend readiness bootstrap and organization state.

Revision ID: 050
Revises: 049
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "050"
down_revision: str | None = "049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORGANIZATION_TYPE_VALUES_OLD = (
    "employer",
    "university",
    "staffing_agency",
    "government",
    "certification_body",
    "hospital",
    "gig_platform",
    "financial_institution",
    "other",
)

ORGANIZATION_TYPE_VALUES_NEW = (
    "employer",
    "university",
    "staffing_agency",
    "background_verification_partner",
    "government",
    "certification_body",
    "hospital",
    "gig_platform",
    "financial_institution",
    "other",
)

ORGANIZATION_VERIFICATION_STATE_VALUES = (
    "setup_incomplete",
    "verification_pending",
    "verified",
    "additional_information_required",
)

ORGANIZATION_INVITATION_STATUS_VALUES = (
    "pending",
    "accepted",
    "declined",
    "cancelled",
    "expired",
)


def _enum(name: str, values: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute("ALTER TYPE organization_type_enum ADD VALUE IF NOT EXISTS 'background_verification_partner'")

    organization_verification_state_enum = _enum(
        "organization_verification_state_enum",
        ORGANIZATION_VERIFICATION_STATE_VALUES,
    )
    organization_invitation_status_enum = _enum(
        "organization_invitation_status_enum",
        ORGANIZATION_INVITATION_STATUS_VALUES,
    )
    organization_role_enum = _enum(
        "organization_role_enum",
        ("owner", "admin", "member", "reviewer"),
    )

    organization_verification_state_enum.create(bind, checkfirst=True)
    organization_invitation_status_enum.create(bind, checkfirst=True)

    op.add_column("users", sa.Column("active_organization_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_active_organization_id_organizations"),
        "users",
        "organizations",
        ["active_organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_users_active_organization_id"), "users", ["active_organization_id"], unique=False)

    op.add_column("organizations", sa.Column("website", sa.String(length=512), nullable=True))
    op.add_column("organizations", sa.Column("industry", sa.String(length=255), nullable=True))
    op.add_column("organizations", sa.Column("location", sa.String(length=255), nullable=True))
    op.add_column("organizations", sa.Column("work_email", sa.String(length=320), nullable=True))
    op.add_column("organizations", sa.Column("domain", sa.String(length=255), nullable=True))
    op.add_column("organizations", sa.Column("domain_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "organizations",
        sa.Column(
            "verification_state",
            organization_verification_state_enum,
            nullable=False,
            server_default="setup_incomplete",
        ),
    )
    op.add_column("organizations", sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("suspension_reason", sa.String(length=512), nullable=True))
    op.create_index(op.f("ix_organizations_domain"), "organizations", ["domain"], unique=False)
    op.create_index(op.f("ix_organizations_suspended_at"), "organizations", ["suspended_at"], unique=False)

    op.add_column("organization_members", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organization_members", sa.Column("suspension_reason", sa.String(length=512), nullable=True))
    op.create_index(op.f("ix_organization_members_suspended_at"), "organization_members", ["suspended_at"], unique=False)

    op.create_table(
        "organization_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invitee_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invitee_email", sa.String(length=320), nullable=False),
        sa.Column("role", organization_role_enum, nullable=False),
        sa.Column(
            "status",
            organization_invitation_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_invitations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=op.f("fk_organization_invitations_invited_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invitee_user_id"],
            ["users.id"],
            name=op.f("fk_organization_invitations_invitee_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_invitations")),
        sa.UniqueConstraint("public_id", name=op.f("uq_organization_invitations_public_id")),
    )
    op.create_index(op.f("ix_organization_invitations_organization_id"), "organization_invitations", ["organization_id"], unique=False)
    op.create_index(op.f("ix_organization_invitations_invited_by_user_id"), "organization_invitations", ["invited_by_user_id"], unique=False)
    op.create_index(op.f("ix_organization_invitations_invitee_user_id"), "organization_invitations", ["invitee_user_id"], unique=False)
    op.create_index(op.f("ix_organization_invitations_invitee_email"), "organization_invitations", ["invitee_email"], unique=False)
    op.create_index(op.f("ix_organization_invitations_status"), "organization_invitations", ["status"], unique=False)
    op.create_index(op.f("ix_organization_invitations_expires_at"), "organization_invitations", ["expires_at"], unique=False)

    op.execute(
        """
        UPDATE organizations
        SET verification_state = 'verified',
            setup_completed_at = COALESCE(setup_completed_at, created_at)
        WHERE EXISTS (
            SELECT 1
            FROM organization_members
            WHERE organization_members.organization_id = organizations.id
        )
        """
    )

    op.execute(
        """
        UPDATE users AS u
        SET active_organization_id = resolved.organization_id
        FROM (
            SELECT DISTINCT ON (organization_members.user_id)
                organization_members.user_id,
                organization_members.organization_id
            FROM organization_members
            ORDER BY organization_members.user_id, organization_members.created_at ASC
        ) AS resolved
        WHERE u.id = resolved.user_id
          AND u.active_organization_id IS NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(op.f("ix_organization_invitations_expires_at"), table_name="organization_invitations")
    op.drop_index(op.f("ix_organization_invitations_status"), table_name="organization_invitations")
    op.drop_index(op.f("ix_organization_invitations_invitee_email"), table_name="organization_invitations")
    op.drop_index(op.f("ix_organization_invitations_invitee_user_id"), table_name="organization_invitations")
    op.drop_index(op.f("ix_organization_invitations_invited_by_user_id"), table_name="organization_invitations")
    op.drop_index(op.f("ix_organization_invitations_organization_id"), table_name="organization_invitations")
    op.drop_table("organization_invitations")

    op.drop_index(op.f("ix_organization_members_suspended_at"), table_name="organization_members")
    op.drop_column("organization_members", "suspension_reason")
    op.drop_column("organization_members", "suspended_at")

    op.drop_index(op.f("ix_organizations_suspended_at"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_domain"), table_name="organizations")
    op.drop_column("organizations", "suspension_reason")
    op.drop_column("organizations", "suspended_at")
    op.drop_column("organizations", "setup_completed_at")
    op.drop_column("organizations", "verification_state")
    op.drop_column("organizations", "domain_verified_at")
    op.drop_column("organizations", "domain")
    op.drop_column("organizations", "work_email")
    op.drop_column("organizations", "location")
    op.drop_column("organizations", "industry")
    op.drop_column("organizations", "website")

    op.drop_index(op.f("ix_users_active_organization_id"), table_name="users")
    op.drop_constraint(op.f("fk_users_active_organization_id_organizations"), "users", type_="foreignkey")
    op.drop_column("users", "active_organization_id")

    organization_invitation_status_enum = _enum(
        "organization_invitation_status_enum",
        ORGANIZATION_INVITATION_STATUS_VALUES,
    )
    organization_verification_state_enum = _enum(
        "organization_verification_state_enum",
        ORGANIZATION_VERIFICATION_STATE_VALUES,
    )
    organization_invitation_status_enum.drop(bind, checkfirst=True)
    organization_verification_state_enum.drop(bind, checkfirst=True)

    op.execute("UPDATE organizations SET organization_type = 'other' WHERE organization_type = 'background_verification_partner'")
    op.execute("ALTER TYPE organization_type_enum RENAME TO organization_type_enum_old")
    _enum("organization_type_enum", ORGANIZATION_TYPE_VALUES_OLD).create(bind, checkfirst=False)
    op.execute(
        """
        ALTER TABLE organizations
        ALTER COLUMN organization_type
        TYPE organization_type_enum
        USING organization_type::text::organization_type_enum
        """
    )
    op.execute("DROP TYPE organization_type_enum_old")

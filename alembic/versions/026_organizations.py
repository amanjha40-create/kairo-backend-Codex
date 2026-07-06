"""Add organizations and organization memberships.

Revision ID: 026
Revises: 025
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.organization.enums import OrganizationRole, OrganizationType

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def _enum(name: str, members: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*members, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    organization_type_enum = _enum(
        "organization_type_enum",
        tuple(member.value for member in OrganizationType),
    )
    organization_role_enum = _enum(
        "organization_role_enum",
        tuple(member.value for member in OrganizationRole),
    )

    organization_type_enum.create(bind, checkfirst=True)
    organization_role_enum.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("organization_type", organization_type_enum, nullable=False),
        sa.Column(
            "verification_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_organizations_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("public_id", name=op.f("uq_organizations_public_id")),
    )
    op.create_index(op.f("ix_organizations_created_by_user_id"), "organizations", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_organizations_name"), "organizations", ["name"], unique=False)

    op.create_table(
        "organization_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", organization_role_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_members_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_members_organization_id_user_id"),
        sa.UniqueConstraint("public_id", name=op.f("uq_organization_members_public_id")),
    )
    op.create_index(op.f("ix_organization_members_organization_id"), "organization_members", ["organization_id"], unique=False)
    op.create_index(op.f("ix_organization_members_role"), "organization_members", ["role"], unique=False)
    op.create_index(op.f("ix_organization_members_user_id"), "organization_members", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    organization_role_enum = _enum(
        "organization_role_enum",
        tuple(member.value for member in OrganizationRole),
    )
    organization_type_enum = _enum(
        "organization_type_enum",
        tuple(member.value for member in OrganizationType),
    )

    op.drop_index(op.f("ix_organization_members_user_id"), table_name="organization_members")
    op.drop_index(op.f("ix_organization_members_role"), table_name="organization_members")
    op.drop_index(op.f("ix_organization_members_organization_id"), table_name="organization_members")
    op.drop_table("organization_members")

    op.drop_index(op.f("ix_organizations_name"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_created_by_user_id"), table_name="organizations")
    op.drop_table("organizations")

    organization_role_enum.drop(bind, checkfirst=True)
    organization_type_enum.drop(bind, checkfirst=True)

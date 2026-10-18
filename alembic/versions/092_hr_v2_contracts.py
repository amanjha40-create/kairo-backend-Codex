"""HR V2 employee, role, logo, preferences, and team invitation contracts.

Revision ID: 092
Revises: 091
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_job_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "organization_id",
            "normalized_name",
            name="uq_organization_job_roles_org_normalized_name",
        ),
    )
    op.create_index(
        "ix_organization_job_roles_organization_id", "organization_job_roles", ["organization_id"]
    )

    op.add_column(
        "organization_people",
        sa.Column(
            "employment_status", sa.String(length=32), server_default="active", nullable=False
        ),
    )
    op.add_column(
        "organization_people", sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "organization_people", sa.Column("department", sa.String(length=255), nullable=True)
    )
    op.add_column("organization_people", sa.Column("joining_date", sa.Date(), nullable=True))
    op.add_column("organization_people", sa.Column("last_working_day", sa.Date(), nullable=True))
    op.create_foreign_key(
        "fk_organization_people_role_id_organization_job_roles",
        "organization_people",
        "organization_job_roles",
        ["role_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_organization_people_employment_status", "organization_people", ["employment_status"]
    )
    op.create_index("ix_organization_people_role_id", "organization_people", ["role_id"])
    op.create_check_constraint(
        op.f("ck_organization_people_employment_status"),
        "organization_people",
        "employment_status IN ('active', 'ex_employee')",
    )
    op.create_check_constraint(
        op.f("ck_organization_people_ex_employee_lwd"),
        "organization_people",
        "employment_status != 'ex_employee' OR last_working_day IS NOT NULL",
    )

    op.add_column(
        "organizations", sa.Column("logo_object_key", sa.String(length=1024), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("logo_content_type", sa.String(length=64), nullable=True)
    )
    op.add_column("organizations", sa.Column("logo_byte_size", sa.BigInteger(), nullable=True))
    op.add_column(
        "organizations",
        sa.Column(
            "verification_preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    op.create_table(
        "organization_logo_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_organization_logo_uploads_organization_id",
        "organization_logo_uploads",
        ["organization_id"],
    )

    op.create_table(
        "organization_activity_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=True),
        sa.Column("subject_public_id", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_organization_activity_events_organization_id",
        "organization_activity_events",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_activity_events_actor_user_id",
        "organization_activity_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_organization_activity_events_event_type", "organization_activity_events", ["event_type"]
    )
    op.create_index(
        "ix_organization_activity_events_created_at", "organization_activity_events", ["created_at"]
    )

    op.add_column(
        "trust_invitations", sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "trust_invitations",
        sa.Column(
            "verification_preferences_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_trust_invitations_role_id_organization_job_roles",
        "trust_invitations",
        "organization_job_roles",
        ["role_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_trust_invitations_role_id", "trust_invitations", ["role_id"])

    for column in (
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_failed_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("organization_invitations", column)
    op.create_index(
        "uq_organization_invitations_token_hash",
        "organization_invitations",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("token_hash IS NOT NULL"),
    )
    op.create_index(
        "ix_organization_invitations_token_expires_at",
        "organization_invitations",
        ["token_expires_at"],
    )


def downgrade():
    op.drop_index(
        "ix_organization_invitations_token_expires_at", table_name="organization_invitations"
    )
    op.drop_index("uq_organization_invitations_token_hash", table_name="organization_invitations")
    for name in (
        "delivery_failed_at",
        "last_sent_at",
        "token_revoked_at",
        "token_used_at",
        "token_expires_at",
        "token_version",
        "token_hash",
    ):
        op.drop_column("organization_invitations", name)
    op.drop_index("ix_trust_invitations_role_id", table_name="trust_invitations")
    op.drop_constraint(
        "fk_trust_invitations_role_id_organization_job_roles",
        "trust_invitations",
        type_="foreignkey",
    )
    op.drop_column("trust_invitations", "verification_preferences_snapshot")
    op.drop_column("trust_invitations", "role_id")
    op.drop_table("organization_activity_events")
    op.drop_table("organization_logo_uploads")
    op.drop_column("organizations", "verification_preferences")
    op.drop_column("organizations", "logo_byte_size")
    op.drop_column("organizations", "logo_content_type")
    op.drop_column("organizations", "logo_object_key")
    op.drop_constraint(
        "ck_organization_people_ex_employee_lwd", "organization_people", type_="check"
    )
    op.drop_constraint(
        "ck_organization_people_employment_status", "organization_people", type_="check"
    )
    op.drop_index("ix_organization_people_role_id", table_name="organization_people")
    op.drop_index("ix_organization_people_employment_status", table_name="organization_people")
    op.drop_constraint(
        "fk_organization_people_role_id_organization_job_roles",
        "organization_people",
        type_="foreignkey",
    )
    for name in ("last_working_day", "joining_date", "department", "role_id", "employment_status"):
        op.drop_column("organization_people", name)
    op.drop_index("ix_organization_job_roles_organization_id", table_name="organization_job_roles")
    op.drop_table("organization_job_roles")

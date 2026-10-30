"""HR-to-Candidate workflow foundation and immutable-history corrections."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None


def upgrade():
    for _name, column in (
        ("department", sa.Column("department", sa.String(255), nullable=True)),
        ("location", sa.Column("location", sa.String(255), nullable=True)),
        ("work_mode", sa.Column("work_mode", sa.String(32), nullable=True)),
        ("status", sa.Column("status", sa.String(32), nullable=False, server_default="active")),
        (
            "created_by_user_id",
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        ),
        (
            "approved_by_user_id",
            sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        ),
        ("approved_at", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)),
        ("rejected_at", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True)),
        ("archived_at", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)),
    ):
        op.add_column("organization_job_roles", column)
    op.create_index("ix_organization_job_roles_status", "organization_job_roles", ["status"])
    op.create_foreign_key(
        "fk_job_roles_created_by",
        "organization_job_roles",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_job_roles_approved_by",
        "organization_job_roles",
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "trust_invitations",
        sa.Column(
            "requirements_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "trust_invitations",
        sa.Column("requirements_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("trust_invitations", sa.Column("candidate_state", sa.String(32), nullable=True))
    op.add_column(
        "trust_invitations", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "trust_invitations", sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "trust_invitations", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "trust_invitations",
        sa.Column("passport_share_link_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "trust_invitations", sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("trust_invitations", sa.Column("consent_version", sa.Integer(), nullable=True))
    op.create_index(
        "ix_trust_invitations_candidate_state", "trust_invitations", ["candidate_state"]
    )
    op.create_index(
        "ix_trust_invitations_passport_share_link_id",
        "trust_invitations",
        ["passport_share_link_id"],
    )
    op.create_foreign_key(
        "fk_trust_invitation_passport_share",
        "trust_invitations",
        "passport_share_links",
        ["passport_share_link_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "organization_invitations", sa.Column("personal_message", sa.Text(), nullable=True)
    )

    op.create_table(
        "organization_person_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "proposed_changes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "before_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("after_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_org_person_corrections_org", "organization_person_corrections", ["organization_id"]
    )
    op.create_index(
        "ix_org_person_corrections_person",
        "organization_person_corrections",
        ["organization_person_id"],
    )
    op.create_index(
        "ix_org_person_corrections_status", "organization_person_corrections", ["status"]
    )


def downgrade():
    op.drop_table("organization_person_corrections")
    op.drop_column("organization_invitations", "personal_message")
    op.drop_constraint(
        "fk_trust_invitation_passport_share", "trust_invitations", type_="foreignkey"
    )
    for column in (
        "consent_version",
        "consented_at",
        "passport_share_link_id",
        "completed_at",
        "declined_at",
        "claimed_at",
        "candidate_state",
        "requirements_version",
        "requirements_snapshot",
    ):
        op.drop_column("trust_invitations", column)
    op.drop_constraint("fk_job_roles_approved_by", "organization_job_roles", type_="foreignkey")
    op.drop_constraint("fk_job_roles_created_by", "organization_job_roles", type_="foreignkey")
    for column in (
        "archived_at",
        "rejected_at",
        "approved_at",
        "approved_by_user_id",
        "created_by_user_id",
        "status",
        "work_mode",
        "location",
        "department",
    ):
        op.drop_column("organization_job_roles", column)

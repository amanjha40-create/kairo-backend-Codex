"""Add the institution People and Alumni projection contract.

Revision ID: 056
Revises: 055
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def _uuid(name: str) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "institution_person_profiles",
        _uuid("id"),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        _uuid("organization_id"),
        _uuid("organization_person_id"),
        sa.Column("lifecycle_status", sa.String(32), nullable=False),
        sa.Column("student_id", sa.String(128), nullable=True),
        sa.Column("degree", sa.String(255), nullable=True),
        sa.Column("programme", sa.String(255), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("admission_date", sa.Date(), nullable=True),
        sa.Column("admission_period", sa.String(32), nullable=True),
        sa.Column("graduation_date", sa.Date(), nullable=True),
        sa.Column("graduation_period", sa.String(32), nullable=True),
        sa.Column(
            "institution_verification_status",
            sa.String(32),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("status_changed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["status_changed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_institution_person_profiles"),
        sa.UniqueConstraint("public_id", name="uq_institution_person_profiles_public_id"),
        sa.UniqueConstraint("organization_person_id", name="uq_institution_person_profiles_person"),
        sa.UniqueConstraint(
            "organization_id", "student_id", name="uq_institution_person_profiles_student_id"
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('current_student', 'alumni', 'withdrawn', 'inactive')",
            name="ck_institution_person_profiles_lifecycle_status",
        ),
    )
    op.create_index(
        "ix_institution_person_profiles_organization_id",
        "institution_person_profiles",
        ["organization_id"],
    )
    op.create_index(
        "ix_institution_person_profiles_lifecycle_status",
        "institution_person_profiles",
        ["lifecycle_status"],
    )
    op.create_index(
        "ix_institution_person_profiles_student_id", "institution_person_profiles", ["student_id"]
    )
    op.create_index(
        "ix_institution_person_profiles_programme", "institution_person_profiles", ["programme"]
    )
    op.create_index(
        "ix_institution_person_profiles_department", "institution_person_profiles", ["department"]
    )
    op.create_index(
        "ix_institution_person_profiles_graduation_period",
        "institution_person_profiles",
        ["graduation_period"],
    )
    op.create_index(
        "ix_institution_person_profiles_institution_verification_status",
        "institution_person_profiles",
        ["institution_verification_status"],
    )

    op.create_table(
        "institution_person_lifecycle_events",
        _uuid("id"),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        _uuid("profile_id"),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["institution_person_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_institution_person_lifecycle_events"),
        sa.UniqueConstraint("public_id", name="uq_institution_person_lifecycle_events_public_id"),
    )
    op.create_index(
        "ix_institution_person_lifecycle_events_profile_id",
        "institution_person_lifecycle_events",
        ["profile_id"],
    )
    op.create_index(
        "ix_institution_person_lifecycle_events_actor_user_id",
        "institution_person_lifecycle_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_institution_person_lifecycle_events_created_at",
        "institution_person_lifecycle_events",
        ["created_at"],
    )

    op.create_table(
        "organization_credential_records",
        _uuid("id"),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        _uuid("organization_id"),
        _uuid("organization_person_id"),
        _uuid("profile_id"),
        sa.Column("credential_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("degree", sa.String(255), nullable=True),
        sa.Column("programme", sa.String(255), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("issued_period", sa.String(32), nullable=True),
        sa.Column("credential_number", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="issued"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["institution_person_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organization_credential_records"),
        sa.UniqueConstraint("public_id", name="uq_organization_credential_records_public_id"),
    )
    op.create_index(
        "ix_organization_credential_records_organization_id",
        "organization_credential_records",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_credential_records_organization_person_id",
        "organization_credential_records",
        ["organization_person_id"],
    )
    op.create_index(
        "ix_organization_credential_records_profile_id",
        "organization_credential_records",
        ["profile_id"],
    )
    op.create_index(
        "ix_organization_credential_records_status", "organization_credential_records", ["status"]
    )

    op.create_table(
        "organization_credential_events",
        _uuid("id"),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        _uuid("credential_id"),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("new_status", sa.String(32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["organization_credential_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_organization_credential_events"),
        sa.UniqueConstraint("public_id", name="uq_organization_credential_events_public_id"),
    )
    op.create_index(
        "ix_organization_credential_events_credential_id",
        "organization_credential_events",
        ["credential_id"],
    )
    op.create_index(
        "ix_organization_credential_events_actor_user_id",
        "organization_credential_events",
        ["actor_user_id"],
    )

    op.create_table(
        "institution_person_consents",
        _uuid("id"),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        _uuid("organization_id"),
        _uuid("organization_person_id"),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "allowed_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("consent_version", sa.String(64), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_institution_person_consents"),
        sa.UniqueConstraint("public_id", name="uq_institution_person_consents_public_id"),
        sa.UniqueConstraint(
            "organization_id", "organization_person_id", name="uq_institution_person_consents_scope"
        ),
    )
    op.create_index(
        "ix_institution_person_consents_organization_id",
        "institution_person_consents",
        ["organization_id"],
    )
    op.create_index(
        "ix_institution_person_consents_organization_person_id",
        "institution_person_consents",
        ["organization_person_id"],
    )
    op.create_index(
        "ix_institution_person_consents_subject_user_id",
        "institution_person_consents",
        ["subject_user_id"],
    )
    op.create_index(
        "ix_institution_person_consents_expires_at", "institution_person_consents", ["expires_at"]
    )
    op.create_index(
        "ix_institution_person_consents_revoked_at", "institution_person_consents", ["revoked_at"]
    )


def downgrade() -> None:
    op.drop_table("institution_person_consents")
    op.drop_table("organization_credential_events")
    op.drop_table("organization_credential_records")
    op.drop_table("institution_person_lifecycle_events")
    op.drop_table("institution_person_profiles")

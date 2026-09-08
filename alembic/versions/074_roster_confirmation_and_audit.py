"""Add roster confirmation outcomes and audit history.

Revision ID: 074
Revises: 073
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_roster_import_rows",
        sa.Column("application_status", sa.String(16), server_default="pending", nullable=False),
    )
    op.add_column(
        "organization_roster_import_rows",
        sa.Column(
            "application_errors",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "organization_roster_import_rows",
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_roster_import_row_application_status",
        "organization_roster_import_rows",
        "application_status IN ('pending', 'ignored', 'created', 'updated', 'failed')",
    )
    op.create_index(
        op.f("ix_organization_roster_import_rows_application_status"),
        "organization_roster_import_rows",
        ["application_status"],
    )
    op.create_index(
        "ix_roster_import_row_import_application_status",
        "organization_roster_import_rows",
        ["import_id", "application_status"],
    )

    op.drop_index(
        "ix_roster_profile_org_employee_id", table_name="organization_person_roster_profiles"
    )
    op.drop_index(
        "ix_roster_profile_org_student_id", table_name="organization_person_roster_profiles"
    )
    op.drop_index(
        "ix_roster_profile_org_roll_number", table_name="organization_person_roster_profiles"
    )
    op.create_index(
        "ix_roster_profile_org_employee_id",
        "organization_person_roster_profiles",
        ["organization_id", "employee_id"],
        unique=True,
        postgresql_where=sa.text("employee_id IS NOT NULL"),
    )
    op.create_index(
        "ix_roster_profile_org_student_id",
        "organization_person_roster_profiles",
        ["organization_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("student_id IS NOT NULL"),
    )
    op.create_index(
        "ix_roster_profile_org_roll_number",
        "organization_person_roster_profiles",
        ["organization_id", "roll_number"],
        unique=True,
        postgresql_where=sa.text("roll_number IS NOT NULL"),
    )

    op.create_table(
        "organization_roster_import_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("row_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('roster_import_confirmed', 'roster_person_created', "
            "'roster_person_updated', 'roster_import_completed', 'roster_import_failed')",
            name="ck_roster_import_audit_action",
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["organization_roster_imports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["organization_person_id"], ["organization_people.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["row_id"], ["organization_roster_import_rows.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("dedupe_key", name="uq_roster_import_audit_dedupe_key"),
    )
    for column in ("public_id", "import_id", "organization_id", "created_at"):
        op.create_index(
            op.f(f"ix_organization_roster_import_audit_events_{column}"),
            "organization_roster_import_audit_events",
            [column],
            unique=column == "public_id",
        )
    op.create_index(
        "ix_roster_import_audit_import_created",
        "organization_roster_import_audit_events",
        ["import_id", "created_at"],
    )
    op.create_index(
        "ix_roster_import_audit_org_created",
        "organization_roster_import_audit_events",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("organization_roster_import_audit_events")

    op.drop_index(
        "ix_roster_profile_org_roll_number", table_name="organization_person_roster_profiles"
    )
    op.drop_index(
        "ix_roster_profile_org_student_id", table_name="organization_person_roster_profiles"
    )
    op.drop_index(
        "ix_roster_profile_org_employee_id", table_name="organization_person_roster_profiles"
    )
    op.create_index(
        "ix_roster_profile_org_employee_id",
        "organization_person_roster_profiles",
        ["organization_id", "employee_id"],
    )
    op.create_index(
        "ix_roster_profile_org_student_id",
        "organization_person_roster_profiles",
        ["organization_id", "student_id"],
    )
    op.create_index(
        "ix_roster_profile_org_roll_number",
        "organization_person_roster_profiles",
        ["organization_id", "roll_number"],
    )

    op.drop_index(
        "ix_roster_import_row_import_application_status",
        table_name="organization_roster_import_rows",
    )
    op.drop_index(
        op.f("ix_organization_roster_import_rows_application_status"),
        table_name="organization_roster_import_rows",
    )
    op.drop_constraint(
        "ck_roster_import_row_application_status",
        "organization_roster_import_rows",
        type_="check",
    )
    op.drop_column("organization_roster_import_rows", "applied_at")
    op.drop_column("organization_roster_import_rows", "application_errors")
    op.drop_column("organization_roster_import_rows", "application_status")

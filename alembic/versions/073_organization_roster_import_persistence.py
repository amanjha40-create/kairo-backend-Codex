"""Add organization roster import persistence.

Revision ID: 073
Revises: 072
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column, sa.Column]:
    return (
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "organization_roster_imports",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("roster_type", sa.String(16), nullable=False),
        sa.Column("source_format", sa.String(8), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("source_storage_key", sa.String(1024), nullable=False),
        sa.Column("state", sa.String(32), server_default="uploaded", nullable=False),
        sa.Column("source_sheet_name", sa.String(255), nullable=True),
        sa.Column("source_sheet_warning", sa.String(512), nullable=True),
        sa.Column(
            "column_mapping",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "warnings", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_new_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_update_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invalid_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("roster_type IN ('employee', 'student')", name="ck_roster_import_type"),
        sa.CheckConstraint(
            "source_format IN ('csv', 'xlsx')", name="ck_roster_import_source_format"
        ),
        sa.CheckConstraint(
            "state IN ('uploaded', 'parsing', 'mapping_required', 'ready_for_review', "
            "'importing', 'completed', 'completed_with_errors', 'failed')",
            name="ck_roster_import_state",
        ),
        sa.CheckConstraint(
            "total_rows >= 0 AND valid_new_count >= 0 AND valid_update_count >= 0 "
            "AND duplicate_count >= 0 AND invalid_count >= 0 AND skipped_count >= 0 "
            "AND created_count >= 0 AND updated_count >= 0 AND failed_count >= 0",
            name="ck_roster_import_nonnegative_counts",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    for column in ("public_id", "organization_id", "uploaded_by_user_id", "roster_type", "state"):
        op.create_index(
            op.f(f"ix_organization_roster_imports_{column}"),
            "organization_roster_imports",
            [column],
            unique=column == "public_id",
        )
    op.create_index(
        "ix_roster_import_org_state", "organization_roster_imports", ["organization_id", "state"]
    )
    op.create_index(
        "ix_roster_import_org_type",
        "organization_roster_imports",
        ["organization_id", "roster_type"],
    )

    op.create_table(
        "organization_roster_import_rows",
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_row_number", sa.Integer(), nullable=False),
        sa.Column(
            "source_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "normalized_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("disposition", sa.String(32), server_default="invalid", nullable=False),
        sa.Column(
            "validation_errors",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("primary_identifier", sa.String(320), nullable=True),
        sa.Column("matched_organization_person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_organization_person_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("original_row_number > 0", name="ck_roster_import_row_positive_number"),
        sa.CheckConstraint(
            "disposition IN ('valid_new', 'valid_update', 'duplicate', 'invalid', 'skipped')",
            name="ck_roster_import_row_disposition",
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["organization_roster_imports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["matched_organization_person_id"], ["organization_people.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["result_organization_person_id"], ["organization_people.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", "original_row_number", name="uq_roster_import_row_number"),
    )
    for column in (
        "import_id",
        "disposition",
        "matched_organization_person_id",
        "result_organization_person_id",
    ):
        op.create_index(
            op.f(f"ix_organization_roster_import_rows_{column}"),
            "organization_roster_import_rows",
            [column],
        )
    op.create_index(
        "ix_roster_import_row_import_disposition",
        "organization_roster_import_rows",
        ["import_id", "disposition"],
    )

    op.create_table(
        "organization_person_roster_profiles",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("roster_type", sa.String(16), nullable=False),
        sa.Column("source", sa.String(32), server_default="organization_import", nullable=False),
        sa.Column("source_import_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("imported_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("employee_id", sa.String(128), nullable=True),
        sa.Column("student_id", sa.String(128), nullable=True),
        sa.Column("roll_number", sa.String(128), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("designation", sa.String(255), nullable=True),
        sa.Column("employment_type", sa.String(64), nullable=True),
        sa.Column("joining_date", sa.Date(), nullable=True),
        sa.Column("joining_date_precision", sa.String(8), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("exit_date_precision", sa.String(8), nullable=True),
        sa.Column("employment_status", sa.String(64), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("degree", sa.String(255), nullable=True),
        sa.Column("program", sa.String(255), nullable=True),
        sa.Column("specialization", sa.String(255), nullable=True),
        sa.Column("admission_date", sa.Date(), nullable=True),
        sa.Column("admission_date_precision", sa.String(8), nullable=True),
        sa.Column("graduation_date", sa.Date(), nullable=True),
        sa.Column("graduation_date_precision", sa.String(8), nullable=True),
        sa.Column("enrollment_status", sa.String(64), nullable=True),
        sa.Column("campus", sa.String(255), nullable=True),
        sa.Column("cohort", sa.String(128), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("roster_type IN ('employee', 'student')", name="ck_roster_profile_type"),
        sa.CheckConstraint("source = 'organization_import'", name="ck_roster_profile_source"),
        sa.CheckConstraint(
            "source_row_number IS NULL OR source_row_number > 0",
            name="ck_roster_profile_source_row",
        ),
        sa.CheckConstraint(
            "joining_date_precision IS NULL OR joining_date_precision IN ('year', 'month', 'day')",
            name="ck_roster_profile_joining_precision",
        ),
        sa.CheckConstraint(
            "exit_date_precision IS NULL OR exit_date_precision IN ('year', 'month', 'day')",
            name="ck_roster_profile_exit_precision",
        ),
        sa.CheckConstraint(
            "admission_date_precision IS NULL "
            "OR admission_date_precision IN ('year', 'month', 'day')",
            name="ck_roster_profile_admission_precision",
        ),
        sa.CheckConstraint(
            "graduation_date_precision IS NULL "
            "OR graduation_date_precision IN ('year', 'month', 'day')",
            name="ck_roster_profile_graduation_precision",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_import_id"], ["organization_roster_imports.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["imported_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_person_id", name="uq_roster_profile_person"),
    )
    for column in (
        "organization_id",
        "organization_person_id",
        "roster_type",
        "source_import_id",
        "imported_by_user_id",
    ):
        op.create_index(
            op.f(f"ix_organization_person_roster_profiles_{column}"),
            "organization_person_roster_profiles",
            [column],
        )
    op.create_index(
        "ix_roster_profile_org_type",
        "organization_person_roster_profiles",
        ["organization_id", "roster_type"],
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


def downgrade() -> None:
    op.drop_table("organization_person_roster_profiles")
    op.drop_table("organization_roster_import_rows")
    op.drop_table("organization_roster_imports")

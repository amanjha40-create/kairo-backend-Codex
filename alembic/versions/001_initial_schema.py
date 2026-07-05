"""Initial schema — auth, refresh tokens, employment verification (PostgreSQL ENUMs).

Revision ID: 001_initial
Revises:
Create Date: 2026-05-06

Single production baseline migration (no follow-on revisions). ENUM types are explicit,
tables drop before ENUM drops on downgrade (FK-safe).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.employment.enums import (
    DocumentExtractionStatus,
    EmploymentDocumentType,
    EmploymentType,
    VerificationAuditAction,
    VerificationStatus,
)

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _enum(name: str, members: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*members, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    verification_status_enum = _enum(
        "verification_status_enum",
        tuple(m.value for m in VerificationStatus),
    )
    employment_type_enum = _enum(
        "employment_type_enum",
        tuple(m.value for m in EmploymentType),
    )
    employment_document_type_enum = _enum(
        "employment_document_type_enum",
        tuple(m.value for m in EmploymentDocumentType),
    )
    document_extraction_status_enum = _enum(
        "document_extraction_status_enum",
        tuple(m.value for m in DocumentExtractionStatus),
    )
    verification_audit_action_enum = _enum(
        "verification_audit_action_enum",
        tuple(m.value for m in VerificationAuditAction),
    )

    verification_status_enum.create(bind, checkfirst=True)
    employment_type_enum.create(bind, checkfirst=True)
    employment_document_type_enum.create(bind, checkfirst=True)
    document_extraction_status_enum.create(bind, checkfirst=True)
    verification_audit_action_enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_deleted_at"), "users", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_id_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
    )
    op.create_index(op.f("ix_refresh_tokens_expires_at"), "refresh_tokens", ["expires_at"], unique=False)
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False)
    op.create_index(op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)

    op.create_table(
        "employments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_full_name", sa.String(length=255), nullable=False),
        sa.Column("subject_email", sa.String(length=320), nullable=True),
        sa.Column("employer_legal_name", sa.String(length=512), nullable=False),
        sa.Column("employer_trade_name", sa.String(length=512), nullable=True),
        sa.Column("job_title", sa.String(length=255), nullable=False),
        sa.Column(
            "employment_type",
            employment_type_enum,
            nullable=False,
            server_default=sa.text(f"'{EmploymentType.FULL_TIME.value}'::employment_type_enum"),
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("work_location_country", sa.String(length=2), nullable=False),
        sa.Column("work_location_region", sa.String(length=128), nullable=True),
        sa.Column(
            "verification_status",
            verification_status_enum,
            nullable=False,
            server_default=sa.text(f"'{VerificationStatus.DRAFT.value}'::verification_status_enum"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewer_summary", sa.Text(), nullable=True),
        sa.Column("pending_info_request", sa.Text(), nullable=True),
        sa.Column("extraction_preview", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_employments_start_before_end",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_employments_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_employments_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employments")),
    )
    op.create_index(op.f("ix_employments_created_by_user_id"), "employments", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_employments_deleted_at"), "employments", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_employments_employer_legal_name"), "employments", ["employer_legal_name"], unique=False)
    op.create_index(op.f("ix_employments_reviewed_by_user_id"), "employments", ["reviewed_by_user_id"], unique=False)
    op.create_index(op.f("ix_employments_start_date"), "employments", ["start_date"], unique=False)
    op.create_index(op.f("ix_employments_subject_email"), "employments", ["subject_email"], unique=False)
    op.create_index(op.f("ix_employments_employment_type"), "employments", ["employment_type"], unique=False)
    op.create_index(op.f("ix_employments_verification_status"), "employments", ["verification_status"], unique=False)

    op.execute(
        sa.text(
            """
            CREATE INDEX ix_employments_active_queue
            ON employments (verification_status, updated_at DESC)
            WHERE deleted_at IS NULL
            """
        )
    )

    op.create_table(
        "employment_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", employment_document_type_enum, nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "extraction_status",
            document_extraction_status_enum,
            nullable=False,
            server_default=sa.text(f"'{DocumentExtractionStatus.PENDING.value}'::document_extraction_status_enum"),
        ),
        sa.Column("extraction_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("extraction_last_error", sa.Text(), nullable=True),
        sa.Column("extraction_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extracted_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["employment_id"],
            ["employments.id"],
            name=op.f("fk_employment_documents_employment_id_employments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name=op.f("fk_employment_documents_uploaded_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employment_documents")),
        sa.UniqueConstraint("object_key", name="uq_employment_documents_object_key"),
    )
    op.create_index(op.f("ix_employment_documents_checksum_sha256"), "employment_documents", ["checksum_sha256"], unique=False)
    op.create_index(op.f("ix_employment_documents_deleted_at"), "employment_documents", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_employment_documents_document_type"), "employment_documents", ["document_type"], unique=False)
    op.create_index(op.f("ix_employment_documents_employment_id"), "employment_documents", ["employment_id"], unique=False)
    op.create_index(op.f("ix_employment_documents_extraction_status"), "employment_documents", ["extraction_status"], unique=False)
    op.create_index(op.f("ix_employment_documents_uploaded_by_user_id"), "employment_documents", ["uploaded_by_user_id"], unique=False)

    op.execute(
        sa.text(
            """
            CREATE INDEX ix_employment_documents_active_by_employment
            ON employment_documents (employment_id, created_at DESC)
            WHERE deleted_at IS NULL
            """
        )
    )

    op.create_table(
        "verification_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", verification_audit_action_enum, nullable=False),
        sa.Column("previous_status", sa.String(length=48), nullable=True),
        sa.Column("new_status", sa.String(length=48), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_verification_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["employment_id"],
            ["employments.id"],
            name=op.f("fk_verification_audit_events_employment_id_employments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_audit_events")),
    )
    op.create_index(op.f("ix_verification_audit_events_action"), "verification_audit_events", ["action"], unique=False)
    op.create_index(op.f("ix_verification_audit_events_actor_user_id"), "verification_audit_events", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_verification_audit_events_created_at"), "verification_audit_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_verification_audit_events_employment_id"), "verification_audit_events", ["employment_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_verification_audit_events_employment_id"), table_name="verification_audit_events")
    op.drop_index(op.f("ix_verification_audit_events_created_at"), table_name="verification_audit_events")
    op.drop_index(op.f("ix_verification_audit_events_actor_user_id"), table_name="verification_audit_events")
    op.drop_index(op.f("ix_verification_audit_events_action"), table_name="verification_audit_events")
    op.drop_table("verification_audit_events")

    op.execute(sa.text("DROP INDEX IF EXISTS ix_employment_documents_active_by_employment"))

    op.drop_index(op.f("ix_employment_documents_uploaded_by_user_id"), table_name="employment_documents")
    op.drop_index(op.f("ix_employment_documents_extraction_status"), table_name="employment_documents")
    op.drop_index(op.f("ix_employment_documents_employment_id"), table_name="employment_documents")
    op.drop_index(op.f("ix_employment_documents_document_type"), table_name="employment_documents")
    op.drop_index(op.f("ix_employment_documents_deleted_at"), table_name="employment_documents")
    op.drop_index(op.f("ix_employment_documents_checksum_sha256"), table_name="employment_documents")
    op.drop_table("employment_documents")

    op.execute(sa.text("DROP INDEX IF EXISTS ix_employments_active_queue"))

    op.drop_index(op.f("ix_employments_verification_status"), table_name="employments")
    op.drop_index(op.f("ix_employments_employment_type"), table_name="employments")

    op.drop_index(op.f("ix_employments_subject_email"), table_name="employments")
    op.drop_index(op.f("ix_employments_start_date"), table_name="employments")
    op.drop_index(op.f("ix_employments_reviewed_by_user_id"), table_name="employments")
    op.drop_index(op.f("ix_employments_employer_legal_name"), table_name="employments")
    op.drop_index(op.f("ix_employments_deleted_at"), table_name="employments")
    op.drop_index(op.f("ix_employments_created_by_user_id"), table_name="employments")
    op.drop_table("employments")

    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_expires_at"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_deleted_at"), table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    _enum("verification_audit_action_enum", tuple(m.value for m in VerificationAuditAction)).drop(bind, checkfirst=True)
    _enum("document_extraction_status_enum", tuple(m.value for m in DocumentExtractionStatus)).drop(bind, checkfirst=True)
    _enum("employment_document_type_enum", tuple(m.value for m in EmploymentDocumentType)).drop(bind, checkfirst=True)
    _enum("employment_type_enum", tuple(m.value for m in EmploymentType)).drop(bind, checkfirst=True)
    _enum("verification_status_enum", tuple(m.value for m in VerificationStatus)).drop(bind, checkfirst=True)

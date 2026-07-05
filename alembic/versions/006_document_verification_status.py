"""Per-document admin verification status.

Revision ID: 006_doc_verify
Revises: 005_employer_verification
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006_doc_verify"
down_revision = "005_employer_verification"
branch_labels = None
depends_on = None

_PENDING_UPLOAD = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def upgrade() -> None:
    for label in ("document_verification_approved", "document_verification_rejected"):
        op.execute(
            sa.text(
                f"""
                DO $upgrade$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_enum e
                    INNER JOIN pg_catalog.pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'verification_audit_action_enum'
                      AND e.enumlabel = '{label}'
                  ) THEN
                    ALTER TYPE verification_audit_action_enum ADD VALUE '{label}';
                  END IF;
                END
                $upgrade$;
                """
            )
        )

    op.add_column(
        "employment_documents",
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_upload",
        ),
    )
    op.add_column(
        "employment_documents",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employment_documents",
        sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "employment_documents",
        sa.Column("reviewer_note", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_employment_documents_verified_by_user_id_users"),
        "employment_documents",
        "users",
        ["verified_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_employment_documents_verification_status"),
        "employment_documents",
        ["verification_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_employment_documents_verified_by_user_id"),
        "employment_documents",
        ["verified_by_user_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            f"""
            UPDATE employment_documents
            SET verification_status = 'pending_review'
            WHERE deleted_at IS NULL
              AND checksum_sha256 != '{_PENDING_UPLOAD}'
            """
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_employment_documents_verified_by_user_id"), table_name="employment_documents")
    op.drop_index(op.f("ix_employment_documents_verification_status"), table_name="employment_documents")
    op.drop_constraint(
        op.f("fk_employment_documents_verified_by_user_id_users"),
        "employment_documents",
        type_="foreignkey",
    )
    op.drop_column("employment_documents", "reviewer_note")
    op.drop_column("employment_documents", "verified_by_user_id")
    op.drop_column("employment_documents", "verified_at")
    op.drop_column("employment_documents", "verification_status")

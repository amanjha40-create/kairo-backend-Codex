"""Canonical employment verification foundation.

Revision ID: 035
Revises: 034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "035"
down_revision: str | None = "034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    contact_type_for_create = postgresql.ENUM(
        "hr", "manager", "founder", "authorized_representative", "other",
        name="verification_contact_type_enum",
    )
    contact_review_status_for_create = postgresql.ENUM(
        "pending", "approved", "changes_requested",
        name="verification_contact_review_status_enum",
    )
    contact_type_for_create.create(op.get_bind(), checkfirst=True)
    contact_review_status_for_create.create(op.get_bind(), checkfirst=True)
    contact_type = postgresql.ENUM(name="verification_contact_type_enum", create_type=False)
    contact_review_status = postgresql.ENUM(
        name="verification_contact_review_status_enum",
        create_type=False,
    )
    op.add_column(
        "verification_requests",
        sa.Column("employment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_verification_requests_employment_id_employments",
        "verification_requests",
        "employments",
        ["employment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_verification_requests_employment_id",
        "verification_requests",
        ["employment_id"],
    )
    op.create_table(
        "verification_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(320), nullable=False),
        sa.Column("contact_role", sa.String(128), nullable=True),
        sa.Column("contact_type", contact_type, nullable=False),
        sa.Column("candidate_note", sa.Text(), nullable=True),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_status", contact_review_status, nullable=False, server_default="pending"),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["verification_request_id"], ["verification_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_verification_contacts_request_id", "verification_contacts", ["verification_request_id"])
    op.create_index("ix_verification_contacts_email", "verification_contacts", ["contact_email"])
    op.create_index("ix_verification_contacts_superseded_at", "verification_contacts", ["superseded_at"])
    op.create_index(
        "uq_verification_contacts_current_request",
        "verification_contacts",
        ["verification_request_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.add_column(
        "verification_request_evidence",
        sa.Column("employment_document_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_verification_request_evidence_employment_document",
        "verification_request_evidence",
        "employment_documents",
        ["employment_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_verification_request_evidence_employment_document_id",
        "verification_request_evidence",
        ["employment_document_id"],
    )
    op.create_index(
        "uq_verification_request_evidence_employment_document",
        "verification_request_evidence",
        ["verification_request_id", "employment_document_id"],
        unique=True,
        postgresql_where=sa.text("employment_document_id IS NOT NULL"),
    )
    op.add_column(
        "employer_verification_requests",
        sa.Column("verification_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_employer_verification_requests_verification_request",
        "employer_verification_requests",
        "verification_requests",
        ["verification_request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_employer_verification_requests_verification_request_id",
        "employer_verification_requests",
        ["verification_request_id"],
        unique=True,
    )
    op.create_index(
        "uq_verification_requests_active_employment",
        "verification_requests",
        ["employment_id"],
        unique=True,
        postgresql_where=sa.text(
            "employment_id IS NOT NULL AND status NOT IN "
            "('verified', 'rejected', 'cancelled', 'expired')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_employer_verification_requests_verification_request_id",
        table_name="employer_verification_requests",
    )
    op.drop_constraint(
        "fk_employer_verification_requests_verification_request",
        "employer_verification_requests",
        type_="foreignkey",
    )
    op.drop_column("employer_verification_requests", "verification_request_id")
    op.drop_index(
        "uq_verification_request_evidence_employment_document",
        table_name="verification_request_evidence",
    )
    op.drop_index(
        "ix_verification_request_evidence_employment_document_id",
        table_name="verification_request_evidence",
    )
    op.drop_constraint(
        "fk_verification_request_evidence_employment_document",
        "verification_request_evidence",
        type_="foreignkey",
    )
    op.drop_column("verification_request_evidence", "employment_document_id")
    op.drop_index("uq_verification_contacts_current_request", table_name="verification_contacts")
    op.drop_index("ix_verification_contacts_superseded_at", table_name="verification_contacts")
    op.drop_index("ix_verification_contacts_email", table_name="verification_contacts")
    op.drop_index("ix_verification_contacts_request_id", table_name="verification_contacts")
    op.drop_table("verification_contacts")
    op.drop_index("uq_verification_requests_active_employment", table_name="verification_requests")
    op.drop_index("ix_verification_requests_employment_id", table_name="verification_requests")
    op.drop_constraint(
        "fk_verification_requests_employment_id_employments",
        "verification_requests",
        type_="foreignkey",
    )
    op.drop_column("verification_requests", "employment_id")
    postgresql.ENUM(name="verification_contact_review_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="verification_contact_type_enum").drop(op.get_bind(), checkfirst=True)

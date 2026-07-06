"""Expand verification requests for admin review workflow.

Revision ID: 029
Revises: 028
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.admin_review.enums import (
    VerificationRequestEvidenceStatus,
    VerificationRequestReviewStatus,
    VerificationReviewCorrectionStatus,
    VerificationReviewNoteType,
    VerificationReviewNoteVisibility,
)
from app.verification_requests.enums import VerificationRequestOriginType, VerificationRequestStatus

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def _enum(name: str, members: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*members, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    for value in (
        VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION.value,
        VerificationRequestStatus.PENDING_ADMIN_REVIEW.value,
        VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS.value,
        VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW.value,
        VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION.value,
        VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION.value,
        VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE.value,
    ):
        op.execute(sa.text(f"ALTER TYPE verification_request_status_enum ADD VALUE IF NOT EXISTS '{value}'"))

    verification_request_origin_type_enum = _enum(
        "verification_request_origin_type_enum",
        tuple(member.value for member in VerificationRequestOriginType),
    )
    verification_request_review_status_enum = _enum(
        "verification_request_review_status_enum",
        tuple(member.value for member in VerificationRequestReviewStatus),
    )
    verification_review_note_visibility_enum = _enum(
        "verification_review_note_visibility_enum",
        tuple(member.value for member in VerificationReviewNoteVisibility),
    )
    verification_review_note_type_enum = _enum(
        "verification_review_note_type_enum",
        tuple(member.value for member in VerificationReviewNoteType),
    )
    verification_review_correction_status_enum = _enum(
        "verification_review_correction_status_enum",
        tuple(member.value for member in VerificationReviewCorrectionStatus),
    )
    verification_request_evidence_status_enum = _enum(
        "verification_request_evidence_status_enum",
        tuple(member.value for member in VerificationRequestEvidenceStatus),
    )

    verification_request_origin_type_enum.create(bind, checkfirst=True)
    verification_request_review_status_enum.create(bind, checkfirst=True)
    verification_review_note_visibility_enum.create(bind, checkfirst=True)
    verification_review_note_type_enum.create(bind, checkfirst=True)
    verification_review_correction_status_enum.create(bind, checkfirst=True)
    verification_request_evidence_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "verification_requests",
        sa.Column(
            "origin_type",
            verification_request_origin_type_enum,
            nullable=False,
            server_default=VerificationRequestOriginType.ORGANIZATION_CREATED.value,
        ),
    )
    op.add_column("verification_requests", sa.Column("target_organization_name", sa.String(length=255), nullable=True))
    op.add_column("verification_requests", sa.Column("target_organization_email", sa.String(length=320), nullable=True))
    op.add_column(
        "verification_requests",
        sa.Column(
            "target_organization_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "verification_requests",
        sa.Column("submitted_for_admin_review_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "verification_requests",
        sa.Column("approved_for_organization_verification_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "verification_requests",
        sa.Column("organization_outreach_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "verification_requests",
        sa.Column("last_subject_resubmitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("verification_requests", "organization_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.create_index(
        op.f("ix_verification_requests_target_organization_name"),
        "verification_requests",
        ["target_organization_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_requests_target_organization_email"),
        "verification_requests",
        ["target_organization_email"],
        unique=False,
    )

    op.create_table(
        "verification_request_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("review_status", verification_request_review_status_enum, nullable=False),
        sa.Column("assigned_reviewer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["verification_request_id"],
            ["verification_requests.id"],
            name=op.f("fk_verification_request_reviews_verification_request_id_verification_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_reviewer_user_id"],
            ["users.id"],
            name=op.f("fk_verification_request_reviews_assigned_reviewer_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["users.id"],
            name=op.f("fk_verification_request_reviews_assigned_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decision_by_user_id"],
            ["users.id"],
            name=op.f("fk_verification_request_reviews_decision_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_request_reviews")),
        sa.UniqueConstraint("public_id", name=op.f("uq_verification_request_reviews_public_id")),
        sa.UniqueConstraint(
            "verification_request_id",
            "review_round",
            name=op.f("uq_verification_request_reviews_verification_request_id_review_round"),
        ),
    )
    op.create_index(
        op.f("ix_verification_request_reviews_verification_request_id"),
        "verification_request_reviews",
        ["verification_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_reviews_assigned_reviewer_user_id"),
        "verification_request_reviews",
        ["assigned_reviewer_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_reviews_assigned_by_user_id"),
        "verification_request_reviews",
        ["assigned_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_reviews_decision_by_user_id"),
        "verification_request_reviews",
        ["decision_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_reviews_review_status"),
        "verification_request_reviews",
        ["review_status"],
        unique=False,
    )

    op.create_table(
        "verification_request_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("field_key", sa.String(length=128), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", verification_request_evidence_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["verification_request_id"],
            ["verification_requests.id"],
            name=op.f("fk_verification_request_evidence_verification_request_id_verification_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["users.id"],
            name=op.f("fk_verification_request_evidence_submitted_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["user_documents.id"],
            name=op.f("fk_verification_request_evidence_document_id_user_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_request_evidence")),
        sa.UniqueConstraint("public_id", name=op.f("uq_verification_request_evidence_public_id")),
    )
    op.create_index(
        op.f("ix_verification_request_evidence_verification_request_id"),
        "verification_request_evidence",
        ["verification_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_evidence_submitted_by_user_id"),
        "verification_request_evidence",
        ["submitted_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_evidence_evidence_type"),
        "verification_request_evidence",
        ["evidence_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_evidence_field_key"),
        "verification_request_evidence",
        ["field_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_evidence_document_id"),
        "verification_request_evidence",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_request_evidence_status"),
        "verification_request_evidence",
        ["status"],
        unique=False,
    )

    op.create_table(
        "verification_review_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_request_review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visibility", verification_review_note_visibility_enum, nullable=False),
        sa.Column("note_type", verification_review_note_type_enum, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["verification_request_review_id"],
            ["verification_request_reviews.id"],
            name=op.f("fk_verification_review_notes_verification_request_review_id_verification_request_reviews"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_verification_review_notes_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_review_notes")),
        sa.UniqueConstraint("public_id", name=op.f("uq_verification_review_notes_public_id")),
    )
    op.create_index(
        op.f("ix_verification_review_notes_verification_request_review_id"),
        "verification_review_notes",
        ["verification_request_review_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_review_notes_author_user_id"),
        "verification_review_notes",
        ["author_user_id"],
        unique=False,
    )

    op.create_table(
        "verification_review_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_request_review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_request_evidence_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", verification_review_correction_status_enum, nullable=False),
        sa.Column("field_key", sa.String(length=128), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("guidance", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["verification_request_review_id"],
            ["verification_request_reviews.id"],
            name=op.f("fk_verification_review_corrections_verification_request_review_id_verification_request_reviews"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verification_request_evidence_id"],
            ["verification_request_evidence.id"],
            name=op.f("fk_verification_review_corrections_verification_request_evidence_id_verification_request_evidence"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_verification_review_corrections_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            name=op.f("fk_verification_review_corrections_resolved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_review_corrections")),
        sa.UniqueConstraint("public_id", name=op.f("uq_verification_review_corrections_public_id")),
    )
    op.create_index(
        op.f("ix_verification_review_corrections_verification_request_review_id"),
        "verification_review_corrections",
        ["verification_request_review_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_review_corrections_verification_request_evidence_id"),
        "verification_review_corrections",
        ["verification_request_evidence_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_review_corrections_requested_by_user_id"),
        "verification_review_corrections",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_review_corrections_resolved_by_user_id"),
        "verification_review_corrections",
        ["resolved_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_review_corrections_status"),
        "verification_review_corrections",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_review_corrections_field_key"),
        "verification_review_corrections",
        ["field_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_verification_review_corrections_field_key"), table_name="verification_review_corrections")
    op.drop_index(op.f("ix_verification_review_corrections_status"), table_name="verification_review_corrections")
    op.drop_index(op.f("ix_verification_review_corrections_resolved_by_user_id"), table_name="verification_review_corrections")
    op.drop_index(op.f("ix_verification_review_corrections_requested_by_user_id"), table_name="verification_review_corrections")
    op.drop_index(op.f("ix_verification_review_corrections_verification_request_evidence_id"), table_name="verification_review_corrections")
    op.drop_index(op.f("ix_verification_review_corrections_verification_request_review_id"), table_name="verification_review_corrections")
    op.drop_table("verification_review_corrections")

    op.drop_index(op.f("ix_verification_review_notes_author_user_id"), table_name="verification_review_notes")
    op.drop_index(op.f("ix_verification_review_notes_verification_request_review_id"), table_name="verification_review_notes")
    op.drop_table("verification_review_notes")

    op.drop_index(op.f("ix_verification_request_evidence_status"), table_name="verification_request_evidence")
    op.drop_index(op.f("ix_verification_request_evidence_document_id"), table_name="verification_request_evidence")
    op.drop_index(op.f("ix_verification_request_evidence_field_key"), table_name="verification_request_evidence")
    op.drop_index(op.f("ix_verification_request_evidence_evidence_type"), table_name="verification_request_evidence")
    op.drop_index(op.f("ix_verification_request_evidence_submitted_by_user_id"), table_name="verification_request_evidence")
    op.drop_index(op.f("ix_verification_request_evidence_verification_request_id"), table_name="verification_request_evidence")
    op.drop_table("verification_request_evidence")

    op.drop_index(op.f("ix_verification_request_reviews_review_status"), table_name="verification_request_reviews")
    op.drop_index(op.f("ix_verification_request_reviews_decision_by_user_id"), table_name="verification_request_reviews")
    op.drop_index(op.f("ix_verification_request_reviews_assigned_by_user_id"), table_name="verification_request_reviews")
    op.drop_index(op.f("ix_verification_request_reviews_assigned_reviewer_user_id"), table_name="verification_request_reviews")
    op.drop_index(op.f("ix_verification_request_reviews_verification_request_id"), table_name="verification_request_reviews")
    op.drop_table("verification_request_reviews")

    op.drop_index(op.f("ix_verification_requests_target_organization_email"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_target_organization_name"), table_name="verification_requests")
    op.alter_column("verification_requests", "organization_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("verification_requests", "last_subject_resubmitted_at")
    op.drop_column("verification_requests", "organization_outreach_sent_at")
    op.drop_column("verification_requests", "approved_for_organization_verification_at")
    op.drop_column("verification_requests", "submitted_for_admin_review_at")
    op.drop_column("verification_requests", "target_organization_metadata")
    op.drop_column("verification_requests", "target_organization_email")
    op.drop_column("verification_requests", "target_organization_name")
    op.drop_column("verification_requests", "origin_type")

    _enum(
        "verification_request_evidence_status_enum",
        tuple(member.value for member in VerificationRequestEvidenceStatus),
    ).drop(op.get_bind(), checkfirst=True)
    _enum(
        "verification_review_correction_status_enum",
        tuple(member.value for member in VerificationReviewCorrectionStatus),
    ).drop(op.get_bind(), checkfirst=True)
    _enum(
        "verification_review_note_type_enum",
        tuple(member.value for member in VerificationReviewNoteType),
    ).drop(op.get_bind(), checkfirst=True)
    _enum(
        "verification_review_note_visibility_enum",
        tuple(member.value for member in VerificationReviewNoteVisibility),
    ).drop(op.get_bind(), checkfirst=True)
    _enum(
        "verification_request_review_status_enum",
        tuple(member.value for member in VerificationRequestReviewStatus),
    ).drop(op.get_bind(), checkfirst=True)
    _enum(
        "verification_request_origin_type_enum",
        tuple(member.value for member in VerificationRequestOriginType),
    ).drop(op.get_bind(), checkfirst=True)

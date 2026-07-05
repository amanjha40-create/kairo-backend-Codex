"""add user_documents, educations, education_documents

Revision ID: 011
Revises: 010
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- user_documents ---
    op.create_table(
        "user_documents",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(48), nullable=False),
        sa.Column("document_number", sa.String(128), nullable=True),
        sa.Column("object_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(48), nullable=False, server_default="pending"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_note", sa.Text, nullable=True),
        sa.Column("expires_at", sa.Date, nullable=True),
        sa.Column("extracted_payload", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_documents_user_id", "user_documents", ["user_id"])
    op.create_index("ix_user_documents_document_type", "user_documents", ["document_type"])
    op.create_index("ix_user_documents_document_number", "user_documents", ["document_number"])
    op.create_index("ix_user_documents_checksum_sha256", "user_documents", ["checksum_sha256"])

    # --- educations ---
    op.create_table(
        "educations",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("institution_name", sa.String(512), nullable=False),
        sa.Column("degree", sa.String(255), nullable=False),
        sa.Column("field_of_study", sa.String(255), nullable=True),
        sa.Column("education_level", sa.String(48), nullable=False),
        sa.Column("grade", sa.String(64), nullable=True),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("is_currently_studying", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("verification_status", sa.String(48), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_educations_user_id", "educations", ["user_id"])
    op.create_index("ix_educations_institution_name", "educations", ["institution_name"])
    op.create_index("ix_educations_education_level", "educations", ["education_level"])
    op.create_index("ix_educations_start_date", "educations", ["start_date"])

    # --- education_documents ---
    op.create_table(
        "education_documents",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("education_id", PGUUID(as_uuid=True), sa.ForeignKey("educations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(48), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(48), nullable=False, server_default="pending"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_note", sa.Text, nullable=True),
        sa.Column("extracted_payload", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_education_documents_education_id", "education_documents", ["education_id"])
    op.create_index("ix_education_documents_uploaded_by_user_id", "education_documents", ["uploaded_by_user_id"])
    op.create_index("ix_education_documents_document_type", "education_documents", ["document_type"])
    op.create_index("ix_education_documents_checksum_sha256", "education_documents", ["checksum_sha256"])


def downgrade() -> None:
    op.drop_table("education_documents")
    op.drop_table("educations")
    op.drop_table("user_documents")

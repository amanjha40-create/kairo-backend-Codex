"""Resume processing foundation.

Revision ID: 039
Revises: 038
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_bucket", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("normalized_filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64)),
        sa.Column("upload_status", sa.String(32), nullable=False, server_default="pending_upload"),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="pending_upload"),
        sa.Column("source", sa.String(32), nullable=False, server_default="candidate_upload"),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_version", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("last_error", sa.Text()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_resume_documents_user_id", "resume_documents", ["user_id"])
    op.create_index("ix_resume_documents_upload_status", "resume_documents", ["upload_status"])
    op.create_index("ix_resume_documents_processing_status", "resume_documents", ["processing_status"])
    op.create_index("ix_resume_documents_checksum_sha256", "resume_documents", ["checksum_sha256"])

    op.create_table(
        "resume_processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resume_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("extraction_provider", sa.String(64), nullable=False, server_default="textract"),
        sa.Column("parsing_provider", sa.String(64), nullable=False, server_default="bedrock"),
        sa.Column("extraction_job_id", sa.String(255)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_category", sa.String(64)),
        sa.Column("sanitized_failure_code", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("parser_schema_version", sa.String(32), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("resume_document_id", "idempotency_key"),
    )
    op.create_index("ix_resume_processing_jobs_resume_document_id", "resume_processing_jobs", ["resume_document_id"])
    op.create_index("ix_resume_processing_jobs_user_id", "resume_processing_jobs", ["user_id"])
    op.create_index("ix_resume_processing_jobs_status", "resume_processing_jobs", ["status"])

    op.create_table(
        "resume_parsed_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_processing_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("structured_result", postgresql.JSONB(), nullable=False),
        sa.Column("parser_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_resume_parsed_results_job_id", "resume_parsed_results", ["job_id"])
    op.create_index("ix_resume_parsed_results_user_id", "resume_parsed_results", ["user_id"])


def downgrade() -> None:
    op.drop_table("resume_parsed_results")
    op.drop_table("resume_processing_jobs")
    op.drop_table("resume_documents")

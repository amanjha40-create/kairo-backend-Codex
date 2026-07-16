"""Resume review, deduplication and import provenance.

Revision ID: 040
Revises: 039
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_review_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("processing_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_processing_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parsed_result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_parsed_results.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_resume_review_sessions_user_id", "resume_review_sessions", ["user_id"])
    op.create_index("ix_resume_review_sessions_resume_document_id", "resume_review_sessions", ["resume_document_id"])
    op.create_index("ix_resume_review_sessions_status", "resume_review_sessions", ["status"])

    op.create_table(
        "resume_review_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("review_session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_review_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_type", sa.String(32), nullable=False),
        sa.Column("source_claim_id", sa.String(64), nullable=False),
        sa.Column("original_payload", postgresql.JSONB(), nullable=False),
        sa.Column("edited_payload", postgresql.JSONB(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("duplicate_status", sa.String(32), nullable=False, server_default="no_match"),
        sa.Column("duplicate_candidates", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("conflict_warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("import_action", sa.String(32), nullable=False, server_default="skip"),
        sa.Column("target_record_id", postgresql.UUID(as_uuid=True)),
        sa.Column("imported_record_type", sa.String(32)),
        sa.Column("imported_record_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_reference", sa.String(512)),
        sa.Column("confidence", sa.Float()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("review_session_id", "source_claim_id"),
    )
    op.create_index("ix_resume_review_items_review_session_id", "resume_review_items", ["review_session_id"])
    op.create_index("ix_resume_review_items_user_id", "resume_review_items", ["user_id"])
    op.create_index("ix_resume_review_items_claim_type", "resume_review_items", ["claim_type"])

    op.create_table(
        "resume_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_review_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="processing"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("linked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key"),
    )
    op.create_index("ix_resume_import_batches_user_id", "resume_import_batches", ["user_id"])
    op.create_index("ix_resume_import_batches_review_session_id", "resume_import_batches", ["review_session_id"])
    op.create_index("ix_resume_import_batches_status", "resume_import_batches", ["status"])

    op.create_table(
        "resume_import_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_review_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("record_type", sa.String(32)),
        sa.Column("record_id", postgresql.UUID(as_uuid=True)),
        sa.Column("sanitized_error_code", sa.String(64)),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("import_batch_id", "review_item_id"),
    )
    op.create_index("ix_resume_import_results_import_batch_id", "resume_import_results", ["import_batch_id"])
    op.create_index("ix_resume_import_results_review_item_id", "resume_import_results", ["review_item_id"])

    op.create_table(
        "resume_record_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("record_type", sa.String(32), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resume_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parsed_result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_parsed_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_review_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_review_items.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resume_import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="resume"),
        sa.Column("original_payload_hash", sa.String(64), nullable=False),
        sa.Column("edited_payload_hash", sa.String(64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_resume_record_provenance_user_id", "resume_record_provenance", ["user_id"])
    op.create_index("ix_resume_record_provenance_record_type", "resume_record_provenance", ["record_type"])
    op.create_index("ix_resume_record_provenance_record_id", "resume_record_provenance", ["record_id"])


def downgrade() -> None:
    op.drop_table("resume_record_provenance")
    op.drop_table("resume_import_results")
    op.drop_table("resume_import_batches")
    op.drop_table("resume_review_items")
    op.drop_table("resume_review_sessions")

"""Private version-bound address document workflow; no historical backfill."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "permanent_address_documents",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "address_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("permanent_address_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("user_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("issued_on", sa.Date()),
        sa.Column("binding", pg.JSONB()),
        sa.UniqueConstraint("document_id"),
        sa.CheckConstraint(
            "status IN ('UPLOADING', 'UPLOADED', 'UNDER_REVIEW', 'MATCH', "
            "'REJECTED', 'NEEDS_CORRECTION', 'SUPERSEDED')",
            name="status_allowed",
        ),
    )
    op.create_index(
        "ix_permanent_address_documents_address_version_id",
        "permanent_address_documents",
        ["address_version_id"],
    )
    op.add_column("permanent_address_reviews", sa.Column("idempotency_key", pg.UUID(as_uuid=True)))
    op.add_column("permanent_address_reviews", sa.Column("request_digest", sa.String(64)))
    op.create_unique_constraint(
        "uq_permanent_address_reviews_address_version_id_idempotency_key",
        "permanent_address_reviews",
        ["address_version_id", "idempotency_key"],
    )


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM permanent_address_documents)
           OR EXISTS (SELECT 1 FROM permanent_address_reviews WHERE idempotency_key IS NOT NULL)
        THEN RAISE EXCEPTION 'address_document_data_requires_explicit_retention_plan';
        END IF;
    END $$""")
    op.drop_constraint(
        "uq_permanent_address_reviews_address_version_id_idempotency_key",
        "permanent_address_reviews",
        type_="unique",
    )
    op.drop_column("permanent_address_reviews", "request_digest")
    op.drop_column("permanent_address_reviews", "idempotency_key")
    op.drop_table("permanent_address_documents")

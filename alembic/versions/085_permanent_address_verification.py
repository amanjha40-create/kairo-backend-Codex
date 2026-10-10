"""Add private, versioned permanent-address verification without legacy backfill."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade():
    op.create_table(
        "permanent_address_versions",
        *identity(),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("claimed_address", pg.JSONB(), nullable=False),
        sa.Column("address_hash", sa.String(64), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("geocode_status", sa.String(32), nullable=False),
        sa.Column("target_encrypted", sa.LargeBinary()),
        sa.Column("target_key_id", sa.String(64)),
        sa.Column("geocode_metadata", pg.JSONB()),
        sa.Column("geocoded_at", sa.DateTime(timezone=True)),
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("user_documents.id", ondelete="SET NULL"),
        ),
        sa.Column("document_checksum", sa.String(64)),
        sa.Column("document_status", sa.String(32), nullable=False),
        sa.Column("evidence_binding", pg.JSONB()),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "version"),
        sa.CheckConstraint("version > 0 AND cycle > 0", name="positive_versions"),
    )
    op.create_index(
        "ix_permanent_address_versions_user_id", "permanent_address_versions", ["user_id"]
    )
    op.create_table(
        "permanent_address_sessions",
        *identity(),
        sa.Column(
            "address_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("permanent_address_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("challenge_hash", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("counted_day", sa.Date()),
        sa.Column("derived_evidence", pg.JSONB()),
        sa.UniqueConstraint("address_version_id", "cycle", "counted_day"),
        sa.CheckConstraint(
            "counted_day IS NULL OR result = 'MATCHED'", name="counted_only_matched"
        ),
    )
    op.create_index(
        "ix_permanent_address_sessions_address_version_id",
        "permanent_address_sessions",
        ["address_version_id"],
    )
    op.create_table(
        "permanent_address_reviews",
        *identity(),
        sa.Column(
            "address_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("permanent_address_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("user_documents.id", ondelete="SET NULL"),
        ),
        sa.Column("document_checksum", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_permanent_address_reviews_address_version_id",
        "permanent_address_reviews",
        ["address_version_id"],
    )
    op.create_table(
        "permanent_address_geocode_budgets",
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("request_count >= 0", name="nonnegative_count"),
    )


def downgrade():
    for table in (
        "permanent_address_geocode_budgets",
        "permanent_address_reviews",
        "permanent_address_sessions",
        "permanent_address_versions",
    ):
        op.drop_table(table)

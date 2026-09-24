"""File-free DigiLocker identity provenance.

Revision ID: 081
Revises: 080
"""

import sqlalchemy as sa

from alembic import op

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "digilocker_identity_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source_connection_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("document_type", sa.String(8), nullable=False),
        sa.Column("issuer_id", sa.String(128), nullable=True),
        sa.Column("issuer_name", sa.String(512), nullable=True),
        sa.Column("provider_reference_fingerprint", sa.String(64), nullable=False),
        sa.Column("consent_purpose", sa.String(32), nullable=False),
        sa.Column("consent_version", sa.String(8), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("integrity_result", sa.String(16), nullable=False),
        sa.Column("match_result", sa.String(24), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_valid_until", sa.Date(), nullable=True),
        sa.Column("profile_revision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_connection_id"], ["digilocker_connections.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "user_id",
            "document_type",
            "provider_reference_fingerprint",
            name="uq_digilocker_identity_document",
        ),
        sa.CheckConstraint("document_type IN ('PANCR','DRVLC')", name="document_type"),
        sa.CheckConstraint(
            "source = 'digilocker' AND source_type = 'issued_document'", name="source"
        ),
        sa.CheckConstraint(
            "consent_purpose = 'identity_verification' AND consent_version = 'v1'", name="consent"
        ),
        sa.CheckConstraint("integrity_result IN ('verified','failed')", name="integrity"),
        sa.CheckConstraint(
            "match_result IN ('VERIFIED_MATCH','PARTIAL_MATCH','MISMATCH','UNABLE_TO_VERIFY')",
            name="match_result",
        ),
        sa.CheckConstraint(
            "(match_result = 'VERIFIED_MATCH' AND verified_at IS NOT NULL "
            "AND integrity_result = 'verified') OR "
            "(match_result != 'VERIFIED_MATCH' AND verified_at IS NULL)",
            name="verified_result",
        ),
        sa.CheckConstraint("provider_reference_fingerprint ~ '^[0-9a-f]{64}$'", name="fingerprint"),
    )
    op.create_index(
        "ix_digilocker_identity_verifications_user_id",
        "digilocker_identity_verifications",
        ["user_id"],
    )
    op.create_index(
        "ix_digilocker_identity_verifications_source_connection_id",
        "digilocker_identity_verifications",
        ["source_connection_id"],
    )


def downgrade():
    op.drop_table("digilocker_identity_verifications")

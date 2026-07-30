"""Link education records and evidence to shared verification requests.

Revision ID: 062
Revises: 061
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "verification_requests",
        sa.Column("education_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_verification_requests_education_id",
        "verification_requests",
        "educations",
        ["education_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_verification_requests_education_id",
        "verification_requests",
        ["education_id"],
    )
    op.add_column(
        "verification_request_evidence",
        sa.Column("education_document_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_verification_request_evidence_education_document_id",
        "verification_request_evidence",
        "education_documents",
        ["education_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_verification_request_evidence_education_document_id",
        "verification_request_evidence",
        ["education_document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_verification_request_evidence_education_document_id",
        table_name="verification_request_evidence",
    )
    op.drop_constraint(
        "fk_verification_request_evidence_education_document_id",
        "verification_request_evidence",
        type_="foreignkey",
    )
    op.drop_column("verification_request_evidence", "education_document_id")
    op.drop_index(
        "ix_verification_requests_education_id",
        table_name="verification_requests",
    )
    op.drop_constraint(
        "fk_verification_requests_education_id",
        "verification_requests",
        type_="foreignkey",
    )
    op.drop_column("verification_requests", "education_id")

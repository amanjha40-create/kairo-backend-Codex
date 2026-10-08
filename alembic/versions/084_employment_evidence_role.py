"""Preserve legacy evidence as unclassified; record explicit roles for new uploads."""

import sqlalchemy as sa
from alembic import op

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("employment_documents", sa.Column("evidence_role", sa.String(16), nullable=True))
    op.create_check_constraint(
        "employment_document_evidence_role",
        "employment_documents",
        "evidence_role IS NULL OR evidence_role IN ('primary', 'supporting')",
    )


def downgrade():
    op.drop_constraint("employment_document_evidence_role", "employment_documents", type_="check")
    op.drop_column("employment_documents", "evidence_role")

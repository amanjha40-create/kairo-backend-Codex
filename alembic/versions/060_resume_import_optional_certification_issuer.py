"""Allow resume-imported certifications to omit issuer metadata.

Revision ID: 060
Revises: 059
"""

from __future__ import annotations

from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("certifications", "issuing_organization", nullable=True)


def downgrade() -> None:
    op.alter_column("certifications", "issuing_organization", nullable=False)

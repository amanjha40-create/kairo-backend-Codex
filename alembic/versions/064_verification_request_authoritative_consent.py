"""Persist authoritative candidate consent metadata on verification requests.

Revision ID: 064
Revises: 063
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("verification_requests", sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("verification_requests", sa.Column("consent_version", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("verification_requests", "consent_version")
    op.drop_column("verification_requests", "consented_at")

"""Complete HR employment verification contract support.

Revision ID: 052
Revises: 051
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "verification_requests",
        sa.Column("organization_internal_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("verification_requests", "organization_internal_note")

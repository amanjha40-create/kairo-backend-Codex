"""Preserve month and year precision for education dates.

Revision ID: 061
Revises: 060
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "educations",
        sa.Column("start_date_precision", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "educations",
        sa.Column("end_date_precision", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("educations", "end_date_precision")
    op.drop_column("educations", "start_date_precision")

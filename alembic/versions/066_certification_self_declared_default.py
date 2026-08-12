"""Correct candidate certification default verification status.

Revision ID: 066
Revises: 065
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "certifications",
        "verification_status",
        existing_type=sa.String(length=48),
        server_default="self_declared",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "certifications",
        "verification_status",
        existing_type=sa.String(length=48),
        server_default="pending",
        existing_nullable=False,
    )

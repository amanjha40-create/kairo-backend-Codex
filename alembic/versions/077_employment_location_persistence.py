"""Persist Employment city and work arrangement.

Revision ID: 077
Revises: 076
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employments",
        sa.Column("work_location_city", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "employments",
        sa.Column("work_arrangement", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "ck_employments_work_arrangement",
        "employments",
        "work_arrangement IS NULL OR work_arrangement IN ('onsite', 'hybrid', 'remote')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_employments_work_arrangement",
        "employments",
        type_="check",
    )
    op.drop_column("employments", "work_arrangement")
    op.drop_column("employments", "work_location_city")

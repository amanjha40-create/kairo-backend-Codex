"""Normalize post-finalization candidate truth for canonical career records.

Revision ID: 065
Revises: 064
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TYPE verification_status_enum "
            "ADD VALUE IF NOT EXISTS 'verified'"
        )
    )
    op.add_column("employments", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("educations", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE employments AS e
            SET verification_status = 'verified',
                verified_at = COALESCE(e.reviewed_at, e.updated_at, e.created_at)
            FROM verification_requests AS vr
            WHERE vr.employment_id = e.id
              AND vr.status = 'verified'
              AND e.verification_status = 'approved'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE educations
            SET verified_at = COALESCE(reviewed_at, updated_at, created_at)
            WHERE verification_status = 'verified'
              AND verified_at IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("educations", "verified_at")
    op.drop_column("employments", "verified_at")
    # PostgreSQL enum labels cannot be removed in place. The added value is left inert on downgrade.
    pass

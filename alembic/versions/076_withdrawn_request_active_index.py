"""Exclude withdrawn requests from the active Employment uniqueness index.

Revision ID: 076
Revises: 075
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


_ORIGINAL_TERMINAL_STATUSES = "('verified', 'rejected', 'cancelled', 'expired')"
_CURRENT_TERMINAL_STATUSES = (
    "('verified', 'rejected', 'unable_to_verify', 'cancelled', 'withdrawn_by_candidate', 'expired')"
)


def _create_active_employment_index(terminal_statuses: str) -> None:
    op.create_index(
        "uq_verification_requests_active_employment",
        "verification_requests",
        ["employment_id"],
        unique=True,
        postgresql_where=sa.text(
            "employment_id IS NOT NULL AND status NOT IN " + terminal_statuses
        ),
    )


def upgrade() -> None:
    op.drop_index(
        "uq_verification_requests_active_employment",
        table_name="verification_requests",
    )
    _create_active_employment_index(_CURRENT_TERMINAL_STATUSES)


def downgrade() -> None:
    op.drop_index(
        "uq_verification_requests_active_employment",
        table_name="verification_requests",
    )
    _create_active_employment_index(_ORIGINAL_TERMINAL_STATUSES)

"""Add final admin quality-review states to verification workflows.

Revision ID: 063
Revises: 062
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TYPE verification_request_status_enum "
            "ADD VALUE IF NOT EXISTS 'pending_admin_quality_review'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TYPE verification_request_status_enum "
            "ADD VALUE IF NOT EXISTS 'unable_to_verify'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TYPE verification_status_enum "
            "ADD VALUE IF NOT EXISTS 'unable_to_verify'"
        )
    )


def downgrade() -> None:
    # PostgreSQL cannot remove enum labels in place. The added values are inert
    # after an application rollback and preserve historical event readability.
    pass

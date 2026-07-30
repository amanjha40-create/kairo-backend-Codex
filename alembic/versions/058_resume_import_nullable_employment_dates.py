"""Allow imported employment drafts to omit dates.

Revision ID: 058
Revises: 057
"""

from __future__ import annotations

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("employments", "start_date", nullable=True)


def downgrade() -> None:
    op.alter_column("employments", "start_date", nullable=False)

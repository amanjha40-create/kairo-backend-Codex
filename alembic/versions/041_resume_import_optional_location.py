"""Allow resume-imported employment records without a location.

Revision ID: 041
Revises: 040
"""

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("employments", "work_location_country", nullable=True)


def downgrade() -> None:
    op.alter_column("employments", "work_location_country", nullable=False)

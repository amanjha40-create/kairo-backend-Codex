"""Add organization-scoped division to People assignments.

Revision ID: 101
Revises: 100
"""

import sqlalchemy as sa

from alembic import op

revision = "101"
down_revision = "100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_people",
        sa.Column("division", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organization_people", "division")

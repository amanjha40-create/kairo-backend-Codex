"""Allow truthful unknown employment types.

Revision ID: 098
Revises: 097
"""

import sqlalchemy as sa

from alembic import op
from app.db.pg_enums import employment_type_enum

revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "employments",
        "employment_type",
        existing_type=employment_type_enum,
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    # Emergency rollback is intentionally lossy: old code cannot represent an
    # unknown type, so NULL rows receive the least-specific enum before NOT NULL.
    op.execute(
        sa.text(
            "UPDATE employments "
            "SET employment_type = 'other'::employment_type_enum "
            "WHERE employment_type IS NULL"
        )
    )
    op.alter_column(
        "employments",
        "employment_type",
        existing_type=employment_type_enum,
        nullable=False,
        server_default=sa.text("'full_time'::employment_type_enum"),
    )

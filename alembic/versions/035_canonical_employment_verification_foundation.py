"""Canonical employment verification foundation.

Revision ID: 035
Revises: 034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "035"
down_revision: str | None = "034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "verification_requests",
        sa.Column("employment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_verification_requests_employment_id_employments",
        "verification_requests",
        "employments",
        ["employment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_verification_requests_employment_id",
        "verification_requests",
        ["employment_id"],
    )
    op.create_index(
        "uq_verification_requests_active_employment",
        "verification_requests",
        ["employment_id"],
        unique=True,
        postgresql_where=sa.text(
            "employment_id IS NOT NULL AND status NOT IN "
            "('verified', 'rejected', 'cancelled', 'expired')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_verification_requests_active_employment", table_name="verification_requests")
    op.drop_index("ix_verification_requests_employment_id", table_name="verification_requests")
    op.drop_constraint(
        "fk_verification_requests_employment_id_employments",
        "verification_requests",
        type_="foreignkey",
    )
    op.drop_column("verification_requests", "employment_id")

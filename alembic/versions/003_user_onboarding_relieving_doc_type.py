"""User employment onboarding timestamp + relieving letter document type.

Revision ID: 003_onboard_relieve
Revises: 002_ver_assign
Create Date: 2026-05-06

Downgrade drops `employment_onboarding_completed_at` only — PostgreSQL ENUM labels are not removed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003_onboard_relieve"
down_revision = "002_ver_assign"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("employment_onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        sa.text(
            """
            DO $upgrade$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_enum e
                INNER JOIN pg_catalog.pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'employment_document_type_enum'
                  AND e.enumlabel = 'relieving_letter'
              ) THEN
                ALTER TYPE employment_document_type_enum ADD VALUE 'relieving_letter';
              END IF;
            END
            $upgrade$;
            """
        )
    )


def downgrade() -> None:
    op.drop_column("users", "employment_onboarding_completed_at")

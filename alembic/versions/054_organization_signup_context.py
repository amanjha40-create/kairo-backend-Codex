"""Add organization signup context and onboarding fields.

Revision ID: 054
Revises: 053
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pending_signups",
        sa.Column(
            "signup_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'candidate'"),
        ),
    )
    op.create_index(
        "ix_pending_signups_signup_kind",
        "pending_signups",
        ["signup_kind"],
        unique=False,
    )
    op.add_column(
        "organizations",
        sa.Column("organization_size", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("hiring_volume", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "hiring_volume")
    op.drop_column("organizations", "organization_size")
    op.drop_index("ix_pending_signups_signup_kind", table_name="pending_signups")
    op.drop_column("pending_signups", "signup_kind")

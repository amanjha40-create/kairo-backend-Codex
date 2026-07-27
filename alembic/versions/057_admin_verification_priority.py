"""Add durable priority to verification requests.

Revision ID: 057
Revises: 056
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "verification_requests",
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
    )
    op.create_check_constraint(
        "ck_verification_requests_priority",
        "verification_requests",
        "priority IN ('low', 'normal', 'high', 'urgent')",
    )
    op.create_index(
        "ix_verification_requests_priority",
        "verification_requests",
        ["priority"],
    )


def downgrade() -> None:
    op.drop_index("ix_verification_requests_priority", table_name="verification_requests")
    op.drop_constraint("ck_verification_requests_priority", "verification_requests", type_="check")
    op.drop_column("verification_requests", "priority")

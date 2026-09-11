"""Add auditable Candidate verification-request withdrawal.

Revision ID: 075
Revises: 074
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TYPE verification_request_status_enum "
            "ADD VALUE IF NOT EXISTS 'withdrawn_by_candidate'"
        )
    )
    op.add_column(
        "verification_requests",
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "verification_requests",
        sa.Column("withdrawn_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "verification_requests",
        sa.Column(
            "claim_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_verification_requests_withdrawn_by_user_id_users",
        "verification_requests",
        "users",
        ["withdrawn_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_verification_requests_withdrawn_at"),
        "verification_requests",
        ["withdrawn_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_requests_withdrawn_by_user_id"),
        "verification_requests",
        ["withdrawn_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_verification_requests_withdrawn_by_user_id"),
        table_name="verification_requests",
    )
    op.drop_index(
        op.f("ix_verification_requests_withdrawn_at"),
        table_name="verification_requests",
    )
    op.drop_constraint(
        "fk_verification_requests_withdrawn_by_user_id_users",
        "verification_requests",
        type_="foreignkey",
    )
    op.drop_column("verification_requests", "claim_snapshot")
    op.drop_column("verification_requests", "withdrawn_by_user_id")
    op.drop_column("verification_requests", "withdrawn_at")
    # The enum label remains so historical event rows stay readable after rollback.

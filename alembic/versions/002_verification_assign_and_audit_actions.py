"""Assign reviewer columns + audit enum extensions.

Revision ID: 002_ver_assign
Revises: 001_initial
Create Date: 2026-05-06

PostgreSQL cannot drop ENUM values safely — downgrade leaves audit enum members in place.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002_ver_assign"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: fresh installs may already include these labels via `001_initial` enum definition.
    for label in ("review_assigned", "reviewer_remark_added"):
        op.execute(
            sa.text(
                f"""
                DO $upgrade$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_enum e
                    INNER JOIN pg_catalog.pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'verification_audit_action_enum'
                      AND e.enumlabel = '{label}'
                  ) THEN
                    ALTER TYPE verification_audit_action_enum ADD VALUE '{label}';
                  END IF;
                END
                $upgrade$;
                """
            )
        )

    op.add_column(
        "employments",
        sa.Column(
            "assigned_reviewer_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "employments",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_employments_assigned_reviewer_user_id_users"),
        "employments",
        "users",
        ["assigned_reviewer_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_employments_assigned_reviewer_user_id"),
        "employments",
        ["assigned_reviewer_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_employments_assigned_reviewer_user_id"), table_name="employments")
    op.drop_constraint(
        op.f("fk_employments_assigned_reviewer_user_id_users"),
        "employments",
        type_="foreignkey",
    )
    op.drop_column("employments", "assigned_at")
    op.drop_column("employments", "assigned_reviewer_user_id")

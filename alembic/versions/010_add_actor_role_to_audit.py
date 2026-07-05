"""add actor_role and actor_name to audit events

Revision ID: 010
Revises: 009
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "verification_audit_events",
        sa.Column("actor_role", sa.String(32), nullable=True),
    )
    op.add_column(
        "verification_audit_events",
        sa.Column("actor_display_name", sa.String(255), nullable=True),
    )

    # Backfill actor_role from current users.role for existing events
    op.execute("""
        UPDATE verification_audit_events e
        SET actor_role = u.role,
            actor_display_name = COALESCE(u.full_name, u.email)
        FROM users u
        WHERE e.actor_user_id = u.id
    """)

    op.create_index(
        "ix_verification_audit_events_actor_role",
        "verification_audit_events",
        ["actor_role"],
    )


def downgrade() -> None:
    op.drop_index("ix_verification_audit_events_actor_role", table_name="verification_audit_events")
    op.drop_column("verification_audit_events", "actor_display_name")
    op.drop_column("verification_audit_events", "actor_role")

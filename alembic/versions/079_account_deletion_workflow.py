"""Durable DB-first account deletion and private-object cleanup.

Revision ID: 079
Revises: 078
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid, time = postgresql.UUID(as_uuid=True), sa.DateTime(timezone=True)
    op.create_table(
        "account_deletions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("user_id", uuid, nullable=False, unique=True),
        sa.Column("storage_bucket", sa.String(255)),
        sa.Column("storage_prefix", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_at", time, nullable=False),
        sa.Column("db_committed_at", time, nullable=False),
        sa.Column("purge_started_at", time),
        sa.Column("completed_at", time),
        sa.Column("next_attempt_at", time, nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_category", sa.String(64)),
        sa.Column("created_at", time, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", time, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('purge_pending','purge_partial','operator_review','complete')",
            name="status",
        ),
        sa.CheckConstraint("retry_count >= 0", name="retry_count"),
    )
    op.create_index("ix_account_deletions_scan", "account_deletions", ["next_attempt_at", "status"])
    op.create_table(
        "account_deletion_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "deletion_id",
            uuid,
            sa.ForeignKey("account_deletions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", uuid),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("object_key", sa.String(1024)),
        sa.Column("scope_prefix", sa.String(1024)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", time, nullable=False),
        sa.Column("last_error_category", sa.String(64)),
        sa.Column("completed_at", time),
        sa.Column("created_at", time, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", time, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "deletion_id", "identity_hash", name="uq_account_deletion_item_identity"
        ),
        sa.CheckConstraint("kind IN ('object','namespace','otp','unresolved')", name="kind"),
        sa.CheckConstraint("status IN ('pending','retry','complete','review')", name="status"),
        sa.CheckConstraint("attempts >= 0", name="attempts"),
    )
    op.create_index(
        "ix_account_deletion_items_scan",
        "account_deletion_items",
        ["deletion_id", "status", "next_attempt_at"],
    )


def downgrade() -> None:
    # Never discard unfinished erasure work during a rollback.
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM account_deletions)")).scalar():
        raise RuntimeError(
            "Account deletion ledger is nonempty; downgrade requires operator review"
        )
    op.drop_table("account_deletion_items")
    op.drop_table("account_deletions")

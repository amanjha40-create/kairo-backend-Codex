"""Add candidate notification center fields and idempotency."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "049"
down_revision: str | None = "048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("category", sa.String(length=32), nullable=False, server_default="system"))
    op.add_column("notifications", sa.Column("title", sa.String(length=160), nullable=False, server_default="Kairo notification"))
    op.add_column("notifications", sa.Column("body", sa.String(length=500), nullable=False, server_default="You have a new notification."))
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_notifications_category", "notifications", ["category"])
    op.create_index("ix_notifications_read_at", "notifications", ["read_at"])
    op.create_index("ix_notifications_dedupe_key", "notifications", ["dedupe_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_notifications_dedupe_key", table_name="notifications")
    op.drop_index("ix_notifications_read_at", table_name="notifications")
    op.drop_index("ix_notifications_category", table_name="notifications")
    op.drop_column("notifications", "read_at")
    op.drop_column("notifications", "dedupe_key")
    op.drop_column("notifications", "body")
    op.drop_column("notifications", "title")
    op.drop_column("notifications", "category")

"""Track user document replacement history.

Revision ID: 045
Revises: 044
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "045"
down_revision: str | None = "044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_documents", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_documents", sa.Column("superseded_by_id", sa.UUID(), nullable=True))
    op.add_column("user_documents", sa.Column("replaces_document_id", sa.UUID(), nullable=True))
    op.create_index("ix_user_documents_superseded_at", "user_documents", ["superseded_at"])
    op.create_foreign_key(
        "fk_user_documents_superseded_by_id",
        "user_documents",
        "user_documents",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_user_documents_replaces_document_id",
        "user_documents",
        "user_documents",
        ["replaces_document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_documents_replaces_document_id", "user_documents", type_="foreignkey")
    op.drop_constraint("fk_user_documents_superseded_by_id", "user_documents", type_="foreignkey")
    op.drop_index("ix_user_documents_superseded_at", table_name="user_documents")
    op.drop_column("user_documents", "replaces_document_id")
    op.drop_column("user_documents", "superseded_by_id")
    op.drop_column("user_documents", "superseded_at")

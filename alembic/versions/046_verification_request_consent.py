"""Persist candidate verification consent details.

Revision ID: 046
Revises: 045
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "046"
down_revision: str | None = "045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("verification_requests", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "verification_requests",
        sa.Column("consented_fields", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "verification_requests",
        sa.Column("consented_evidence_scope", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("verification_requests", "consented_evidence_scope")
    op.drop_column("verification_requests", "consented_fields")
    op.drop_column("verification_requests", "accepted_at")

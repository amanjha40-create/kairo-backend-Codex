"""Separate explicit evidence inspection from disposition; no backfill."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "088"
down_revision = "087"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "verification_request_evidence",
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "verification_request_evidence",
        sa.Column(
            "reviewed_by_user_id",
            pg.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_evidence_reviewed_by",
        "verification_request_evidence",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_evidence_reviewed_by", "verification_request_evidence", type_="foreignkey"
    )
    op.drop_column("verification_request_evidence", "reviewed_by_user_id")
    op.drop_column("verification_request_evidence", "reviewed_at")

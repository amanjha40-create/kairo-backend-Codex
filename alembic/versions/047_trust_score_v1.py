"""Add versioned, explainable Trust Score V1 snapshots and consent."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "047"
down_revision: str | None = "046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("trust_score_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("trust_score_consent_version", sa.String(length=64), nullable=True))
    op.create_table(
        "trust_score_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("score_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("verification_completeness_percentage", sa.Integer(), nullable=False),
        sa.Column("domain_scores", JSONB(), nullable=False),
        sa.Column("positive_contributors", JSONB(), nullable=False),
        sa.Column("negative_contributors", JSONB(), nullable=False),
        sa.Column("critical_overrides", JSONB(), nullable=False),
        sa.Column("manual_review_reason", sa.String(length=512), nullable=True),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trust_score_snapshots_user_id", "trust_score_snapshots", ["user_id"])
    op.create_index("ix_trust_score_snapshots_score_version", "trust_score_snapshots", ["score_version"])
    op.create_index("ix_trust_score_snapshots_status", "trust_score_snapshots", ["status"])


def downgrade() -> None:
    op.drop_index("ix_trust_score_snapshots_status", table_name="trust_score_snapshots")
    op.drop_index("ix_trust_score_snapshots_score_version", table_name="trust_score_snapshots")
    op.drop_index("ix_trust_score_snapshots_user_id", table_name="trust_score_snapshots")
    op.drop_table("trust_score_snapshots")
    op.drop_column("users", "trust_score_consent_version")
    op.drop_column("users", "trust_score_consent_at")

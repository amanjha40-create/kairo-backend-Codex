"""Add candidate verification response fields.

Revision ID: 044
Revises: 043
"""

from alembic import op
import sqlalchemy as sa

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("verification_requests")}
    if "candidate_response" not in existing:
        op.add_column("verification_requests", sa.Column("candidate_response", sa.String(length=4000), nullable=True))
    if "candidate_response_submitted_at" not in existing:
        op.add_column(
            "verification_requests",
            sa.Column("candidate_response_submitted_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("verification_requests", "candidate_response_submitted_at")
    op.drop_column("verification_requests", "candidate_response")

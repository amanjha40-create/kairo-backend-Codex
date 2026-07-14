"""Add employer verification portal security and response metadata.

Revision ID: 038
Revises: 037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "038"
down_revision: str | None = "037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("employer_verification_requests", sa.Column("viewed_at", sa.DateTime(timezone=True)))
    op.add_column("employer_verification_requests", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.add_column(
        "employer_verification_requests",
        sa.Column("revoked_by_user_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "employer_verification_requests",
        sa.Column(
            "response_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_employer_verification_requests_revoked_by_user_id_users",
        "employer_verification_requests",
        "users",
        ["revoked_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_employer_verification_requests_revoked_at",
        "employer_verification_requests",
        ["revoked_at"],
    )
    op.create_index(
        "ix_employer_verification_requests_revoked_by_user_id",
        "employer_verification_requests",
        ["revoked_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_employer_verification_requests_revoked_by_user_id", table_name="employer_verification_requests")
    op.drop_index("ix_employer_verification_requests_revoked_at", table_name="employer_verification_requests")
    op.drop_constraint(
        "fk_employer_verification_requests_revoked_by_user_id_users",
        "employer_verification_requests",
        type_="foreignkey",
    )
    op.drop_column("employer_verification_requests", "response_metadata")
    op.drop_column("employer_verification_requests", "revoked_by_user_id")
    op.drop_column("employer_verification_requests", "revoked_at")
    op.drop_column("employer_verification_requests", "viewed_at")

"""Add stable public identifiers to employer verification requests.

Revision ID: 037
Revises: 036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "037"
down_revision: str | None = "036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employer_verification_requests",
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE employer_verification_requests "
            "SET public_id = gen_random_uuid() WHERE public_id IS NULL"
        )
    )
    op.alter_column("employer_verification_requests", "public_id", nullable=False)
    op.create_index(
        "ix_employer_verification_requests_public_id",
        "employer_verification_requests",
        ["public_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employer_verification_requests_public_id",
        table_name="employer_verification_requests",
    )
    op.drop_column("employer_verification_requests", "public_id")

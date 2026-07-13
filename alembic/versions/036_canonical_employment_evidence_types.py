"""Add canonical employment evidence types.

Revision ID: 036
Revises: 035
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "036"
down_revision: str | None = "035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CANONICAL_TYPES = (
    "appointment_letter",
    "experience_letter",
    "payslip",
    "employment_id_card",
    "contract",
    "bank_statement",
)


def upgrade() -> None:
    for value in CANONICAL_TYPES:
        op.execute(
            sa.text(
                f"ALTER TYPE employment_document_type_enum ADD VALUE IF NOT EXISTS '{value}'"
            )
        )


def downgrade() -> None:
    # PostgreSQL enum values are retained to preserve historical rows and compatibility.
    pass

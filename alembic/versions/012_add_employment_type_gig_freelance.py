"""Add gig and freelance to employment_type enum

Revision ID: 012
Revises: 011
Create Date: 2026-06-14
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL: add new values to the existing enum type.
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction, so we use COMMIT trick
    # or rely on the fact that Alembic runs each migration in its own transaction
    # and PostgreSQL 12+ supports ADD VALUE within a transaction block.
    op.execute("ALTER TYPE employment_type_enum ADD VALUE IF NOT EXISTS 'gig'")
    op.execute("ALTER TYPE employment_type_enum ADD VALUE IF NOT EXISTS 'freelance'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the type.
    # Safe no-op: just leave the values in place.
    pass

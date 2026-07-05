"""Add verifier_remarks to internships and freelance_contracts

Revision ID: 022
Revises: 021
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("internships", sa.Column("verifier_remarks", sa.Text(), nullable=True))
    op.add_column("freelance_contracts", sa.Column("verifier_remarks", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("freelance_contracts", "verifier_remarks")
    op.drop_column("internships", "verifier_remarks")

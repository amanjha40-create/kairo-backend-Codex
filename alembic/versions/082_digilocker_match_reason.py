"""Add privacy-safe match reason, without guessing historical results.

Revision ID: 082
Revises: 081
"""

import sqlalchemy as sa

from alembic import op

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "digilocker_identity_verifications", sa.Column("match_reason", sa.String(32), nullable=True)
    )
    op.create_check_constraint(
        "match_reason",
        "digilocker_identity_verifications",
        "match_reason IS NULL OR match_reason IN ('NAME_MISMATCH','DOB_MISMATCH',"
        "'NAME_AND_DOB_MISMATCH','REQUIRED_FIELD_MISSING','OTHER')",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_digilocker_identity_verifications_match_reason"),
        "digilocker_identity_verifications",
        type_="check",
    )
    op.drop_column("digilocker_identity_verifications", "match_reason")

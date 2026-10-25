"""Persist display-only PAN and Driving Licence identifiers without raw values."""

import sqlalchemy as sa

from alembic import op

revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "digilocker_identity_verifications",
        sa.Column("masked_identifier", sa.String(12), nullable=True),
    )
    op.create_check_constraint(
        "ck_digilocker_identity_verifications_masked_identifier",
        "digilocker_identity_verifications",
        "masked_identifier IS NULL OR "
        "(document_type = 'PANCR' AND masked_identifier ~ '^••••••[A-Z0-9]{4}$') OR "
        "(document_type = 'DRVLC' AND masked_identifier ~ '^••••••••[A-Z0-9]{4}$')",
    )


def downgrade():
    op.drop_constraint(
        "ck_digilocker_identity_verifications_masked_identifier",
        "digilocker_identity_verifications",
        type_="check",
    )
    op.drop_column("digilocker_identity_verifications", "masked_identifier")

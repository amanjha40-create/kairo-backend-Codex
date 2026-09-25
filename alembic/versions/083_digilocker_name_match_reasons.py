"""Allow private deterministic name-match reasons without changing identity data.

Revision ID: 083
Revises: 082
"""

from alembic import op

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None

TABLE = "digilocker_identity_verifications"
OLD_REASONS = (
    "'NAME_MISMATCH','DOB_MISMATCH','NAME_AND_DOB_MISMATCH','REQUIRED_FIELD_MISSING','OTHER'"
)


def _replace(reasons):
    op.drop_constraint(
        op.f("ck_digilocker_identity_verifications_match_reason"), TABLE, type_="check"
    )
    op.create_check_constraint(
        "match_reason", TABLE, f"match_reason IS NULL OR match_reason IN ({reasons})"
    )


def upgrade():
    _replace(OLD_REASONS + ",'NAME_EXACT_MATCH','FIRST_LAST_MATCH_MIDDLE_IGNORED'")


def downgrade():
    # Fail closed if new reasons exist; never erase provenance to force a downgrade.
    _replace(OLD_REASONS)

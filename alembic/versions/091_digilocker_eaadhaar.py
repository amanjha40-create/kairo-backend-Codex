"""Dedicated file-free e-Aadhaar provenance; no row rewrite.

Revision ID: 091
Revises: 090
"""

import sqlalchemy as sa

from alembic import op

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None
TABLE = "digilocker_identity_verifications"


def replace_checks(extended):
    for name in ("document_type", "source"):
        op.drop_constraint(op.f(f"ck_{TABLE}_{name}"), TABLE, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_document_type"),
        TABLE,
        "document_type IN ('PANCR','DRVLC','EAADHAAR')"
        if extended
        else "document_type IN ('PANCR','DRVLC')",
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_source"),
        TABLE,
        "source = 'digilocker' AND ((document_type IN ('PANCR','DRVLC') "
        "AND source_type = 'issued_document') OR "
        "(document_type = 'EAADHAAR' AND source_type = 'eaadhaar'))"
        if extended
        else "source = 'digilocker' AND source_type = 'issued_document'",
    )


def upgrade():
    replace_checks(True)


def downgrade():
    # Serialize the guard with writes so no Aadhaar row can slip past the check.
    op.execute(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE")
    if (
        op.get_bind()
        .execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {TABLE} WHERE document_type = 'EAADHAAR')"))
        .scalar()
    ):
        raise RuntimeError("Cannot downgrade 091 while e-Aadhaar provenance exists")
    replace_checks(False)

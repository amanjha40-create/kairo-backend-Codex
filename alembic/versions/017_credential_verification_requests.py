"""Generic credential verification requests (internship / freelance magic-link).

Revision ID: 017
Revises: 016
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential_verification_requests",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("subject_type", sa.String(48), nullable=False),
        sa.Column("subject_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("verifier_email", sa.String(320), nullable=False),
        sa.Column("relationship_to_subject", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("remarks", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("subject_type", "subject_id", name="uq_credential_verif_subject"),
        sa.UniqueConstraint("token_hash", name="uq_credential_verif_token_hash"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credential_verif_subject_type "
        "ON credential_verification_requests (subject_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credential_verif_subject_id "
        "ON credential_verification_requests (subject_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credential_verif_verifier_email "
        "ON credential_verification_requests (verifier_email)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credential_verif_token_hash "
        "ON credential_verification_requests (token_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credential_verif_expires_at "
        "ON credential_verification_requests (expires_at)"
    )


def downgrade() -> None:
    op.drop_table("credential_verification_requests")

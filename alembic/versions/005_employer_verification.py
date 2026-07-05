"""Employer confirmation verification — method column + request table.

Revision ID: 005_employer_verification
Revises: 004_email_verify
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005_employer_verification"
down_revision = "004_email_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for label in (
        "employer_verification_requested",
        "employer_verification_confirmed",
        "employer_verification_declined",
    ):
        op.execute(
            sa.text(
                f"""
                DO $upgrade$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_enum e
                    INNER JOIN pg_catalog.pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'verification_audit_action_enum'
                      AND e.enumlabel = '{label}'
                  ) THEN
                    ALTER TYPE verification_audit_action_enum ADD VALUE '{label}';
                  END IF;
                END
                $upgrade$;
                """
            )
        )

    op.add_column(
        "employments",
        sa.Column(
            "verification_method",
            sa.String(length=32),
            nullable=False,
            server_default="document",
        ),
    )
    op.create_index(
        op.f("ix_employments_verification_method"),
        "employments",
        ["verification_method"],
        unique=False,
    )

    op.create_table(
        "employer_verification_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employment_id", sa.Uuid(), nullable=False),
        sa.Column("contact_name", sa.String(length=255), nullable=False),
        sa.Column("verifier_email", sa.String(length=320), nullable=False),
        sa.Column("relationship_to_subject", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["employment_id"],
            ["employments.id"],
            name=op.f("fk_employer_verification_requests_employment_id_employments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employer_verification_requests")),
        sa.UniqueConstraint("employment_id", name=op.f("uq_employer_verification_requests_employment_id")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_employer_verification_requests_token_hash")),
    )
    op.create_index(
        op.f("ix_employer_verification_requests_employment_id"),
        "employer_verification_requests",
        ["employment_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_employer_verification_requests_expires_at"),
        "employer_verification_requests",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_employer_verification_requests_token_hash"),
        "employer_verification_requests",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_employer_verification_requests_verifier_email"),
        "employer_verification_requests",
        ["verifier_email"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_employer_verification_requests_verifier_email"),
        table_name="employer_verification_requests",
    )
    op.drop_index(
        op.f("ix_employer_verification_requests_token_hash"),
        table_name="employer_verification_requests",
    )
    op.drop_index(
        op.f("ix_employer_verification_requests_expires_at"),
        table_name="employer_verification_requests",
    )
    op.drop_index(
        op.f("ix_employer_verification_requests_employment_id"),
        table_name="employer_verification_requests",
    )
    op.drop_table("employer_verification_requests")
    op.drop_index(op.f("ix_employments_verification_method"), table_name="employments")
    op.drop_column("employments", "verification_method")

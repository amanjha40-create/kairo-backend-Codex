"""Allow resume-imported optional metadata to remain incomplete.

Revision ID: 059
Revises: 058
"""

from __future__ import annotations

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("educations", "degree", nullable=True)
    op.alter_column("educations", "education_level", nullable=True)
    op.alter_column("educations", "start_date", nullable=True)
    op.alter_column("certifications", "issued_date", nullable=True)
    op.alter_column("internships", "start_date", nullable=True)
    op.alter_column("internships", "company_name", nullable=True)
    op.alter_column("internships", "role", nullable=True)
    op.alter_column("freelance_contracts", "start_date", nullable=True)
    op.alter_column("freelance_contracts", "client_name", nullable=True)
    op.alter_column("freelance_contracts", "project_title", nullable=True)
    op.alter_column("gig_platforms", "started_at", nullable=True)
    op.alter_column("gig_platforms", "platform_name", nullable=True)
    op.alter_column("gig_platforms", "partner_role", nullable=True)


def downgrade() -> None:
    op.alter_column("certifications", "issued_date", nullable=False)
    op.alter_column("educations", "start_date", nullable=False)
    op.alter_column("educations", "education_level", nullable=False)
    op.alter_column("educations", "degree", nullable=False)
    op.alter_column("gig_platforms", "partner_role", nullable=False)
    op.alter_column("gig_platforms", "platform_name", nullable=False)
    op.alter_column("gig_platforms", "started_at", nullable=False)
    op.alter_column("freelance_contracts", "project_title", nullable=False)
    op.alter_column("freelance_contracts", "client_name", nullable=False)
    op.alter_column("freelance_contracts", "start_date", nullable=False)
    op.alter_column("internships", "role", nullable=False)
    op.alter_column("internships", "company_name", nullable=False)
    op.alter_column("internships", "start_date", nullable=False)

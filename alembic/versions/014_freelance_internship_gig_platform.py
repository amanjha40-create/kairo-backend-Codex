"""Add freelance_contracts, internships, gig_platforms tables

Revision ID: 014
Revises: 013
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "freelance_contracts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("client_name", sa.String(512), nullable=False),
        sa.Column("project_title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_ongoing", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verification_status", sa.String(48), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_freelance_contracts_user_id", "freelance_contracts", ["user_id"])

    op.create_table(
        "internships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("company_name", sa.String(512), nullable=False),
        sa.Column("role", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_ongoing", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("stipend_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("stipend_currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("verification_status", sa.String(48), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_internships_user_id", "internships", ["user_id"])

    op.create_table(
        "gig_platforms",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("platform_name", sa.String(256), nullable=False),
        sa.Column("partner_role", sa.String(256), nullable=False),
        sa.Column("started_at", sa.Date(), nullable=False),
        sa.Column("ended_at", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("partner_id", sa.String(256), nullable=True),
        sa.Column("rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("verification_status", sa.String(48), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gig_platforms_user_id", "gig_platforms", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_gig_platforms_user_id", "gig_platforms")
    op.drop_table("gig_platforms")
    op.drop_index("ix_internships_user_id", "internships")
    op.drop_table("internships")
    op.drop_index("ix_freelance_contracts_user_id", "freelance_contracts")
    op.drop_table("freelance_contracts")

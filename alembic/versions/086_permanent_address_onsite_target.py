"""Add onsite target provenance; no legacy eligibility backfill."""

import sqlalchemy as sa

from alembic import op

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade():
    table = "permanent_address_versions"
    op.add_column(table, sa.Column("target_source", sa.String(32)))
    op.add_column(table, sa.Column("target_status", sa.String(32)))
    op.add_column(table, sa.Column("target_confirmed_at", sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column("target_confirmation_reason", sa.String(64)))
    op.create_check_constraint(
        "target_source_allowed",
        table,
        "target_source IN ('provider_geocode', 'onsite_confirmation')",
    )
    op.create_check_constraint(
        "target_status_allowed",
        table,
        "target_status IN ('active', 'confirmation_required', 'needs_review', 'superseded')",
    )


def downgrade():
    table = "permanent_address_versions"
    op.drop_constraint("target_status_allowed", table, type_="check")
    op.drop_constraint("target_source_allowed", table, type_="check")
    for name in (
        "target_confirmation_reason",
        "target_confirmed_at",
        "target_status",
        "target_source",
    ):
        op.drop_column(table, name)

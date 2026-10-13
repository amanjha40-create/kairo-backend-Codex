"""Prospective encrypted manual location review; no historical backfill."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "089"
down_revision = "088"
branch_labels = None
depends_on = None

V = "permanent_address_versions"
S = "permanent_address_sessions"


def upgrade():
    op.alter_column(V, "target_source", existing_type=sa.String(32), type_=sa.String(64))
    for column in (
        sa.Column("pending_target_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("pending_target_key_id", sa.String(64), nullable=True),
        sa.Column("manual_review_status", sa.String(32), nullable=True),
        sa.Column("manual_resolutions", pg.JSONB(), nullable=True),
    ):
        op.add_column(S, column)
    op.drop_constraint(op.f("ck_permanent_address_versions_target_source_allowed"), V)
    op.create_check_constraint(
        "target_source_allowed",
        V,
        "target_source IN ('provider_geocode', 'onsite_confirmation', "
        "'onsite_confirmation_manual_review')",
    )
    op.drop_constraint(op.f("ck_permanent_address_sessions_counted_only_matched"), S)
    op.create_check_constraint(
        "counted_only_matched",
        S,
        "counted_day IS NULL OR result = 'MATCHED' OR "
        "(result = 'NEEDS_REVIEW' AND COALESCE(manual_review_status = 'approved', false))",
    )
    op.create_check_constraint(
        "pending_target_pair",
        S,
        "(pending_target_encrypted IS NULL) = (pending_target_key_id IS NULL)",
    )
    op.create_check_constraint(
        "manual_review_status_allowed",
        S,
        "manual_review_status IN ('pending', 'additional_evidence_requested', "
        "'approved', 'rejected', 'correction_requested', 'invalidated')",
    )


def downgrade():
    # Never silently discard sensitive pending evidence or accepted dispositions.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM permanent_address_sessions
                   WHERE manual_review_status IS NOT NULL
                      OR pending_target_encrypted IS NOT NULL
                      OR manual_resolutions IS NOT NULL)
        THEN RAISE EXCEPTION 'manual_review_data_requires_explicit_retention_plan';
        END IF;
    END $$""")
    for name in ("counted_only_matched", "pending_target_pair", "manual_review_status_allowed"):
        op.drop_constraint(op.f(f"ck_{S}_{name}"), S)
    op.create_check_constraint(
        "counted_only_matched", S, "counted_day IS NULL OR result = 'MATCHED'"
    )
    op.drop_constraint(op.f("ck_permanent_address_versions_target_source_allowed"), V)
    op.create_check_constraint(
        "target_source_allowed", V, "target_source IN ('provider_geocode', 'onsite_confirmation')"
    )
    for name in (
        "manual_resolutions",
        "manual_review_status",
        "pending_target_key_id",
        "pending_target_encrypted",
    ):
        op.drop_column(S, name)
    op.alter_column(V, "target_source", existing_type=sa.String(64), type_=sa.String(32))

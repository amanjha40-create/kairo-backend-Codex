"""Private employment references; additive, no verification/score backfill."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))
        for name in ("created_at", "updated_at")
    ]


def upgrade():
    op.create_table(
        "employment_references",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("employments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(32), nullable=False),
        *[
            sa.Column(name, pg.JSONB(), nullable=False)
            for name in ("nomination", "validation", "answers")
        ],
        sa.Column(
            "hr_request_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("employer_verification_requests.id", ondelete="SET NULL"),
        ),
        *[
            sa.Column(name, sa.DateTime(timezone=True))
            for name in ("nominated_at", "validated_at", "completed_at", "superseded_at")
        ],
        *timestamps(),
        sa.CheckConstraint(
            "kind IN ('hr_reference', 'reporting_manager_reference')", name="reference_kind"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'cannot_confirm', 'awaiting_hr_validation', "
            "'ready_to_invite', 'invitation_sent', 'opened', 'completed', 'declined', "
            "'expired', 'needs_review')",
            name="reference_status",
        ),
    )
    op.create_index(
        "ix_employment_references_employment_id", "employment_references", ["employment_id"]
    )
    op.create_index(
        "uq_employment_reference_active",
        "employment_references",
        ["employment_id", "kind"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_index(
        "uq_employment_reference_hr",
        "employment_references",
        ["employment_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'hr_reference'"),
    )
    op.create_table(
        "employment_reference_invitations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reference_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("employment_references.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *[
            sa.Column(name, sa.DateTime(timezone=True))
            for name in ("revoked_at", "sent_at", "opened_at", "responded_at")
        ],
        sa.Column("delivery_status", sa.String(32), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("reference_id", "idempotency_key", name="uq_reference_send_key"),
    )
    op.create_index(
        "ix_employment_reference_invitations_reference_id",
        "employment_reference_invitations",
        ["reference_id"],
    )
    op.create_index(
        "uq_reference_live_token",
        "employment_reference_invitations",
        ["reference_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "employment_reference_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reference_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("employment_references.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_employment_reference_events_reference_id",
        "employment_reference_events",
        ["reference_id"],
    )


def downgrade():
    for table in (
        "employment_reference_events",
        "employment_reference_invitations",
        "employment_references",
    ):
        op.drop_table(table)

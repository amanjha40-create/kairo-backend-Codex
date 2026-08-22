"""Add Trust & Safety investigations and signals.

Revision ID: 068
Revises: 067
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trust_safety_investigations",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("assigned_admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dismissal_reason", sa.Text(), nullable=True),
        sa.Column("first_signal_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assigned_admin_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dismissed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_assigned_admin_user_id"),
        "trust_safety_investigations",
        ["assigned_admin_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_created_by_user_id"),
        "trust_safety_investigations",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_dismissed_by_user_id"),
        "trust_safety_investigations",
        ["dismissed_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_public_id"),
        "trust_safety_investigations",
        ["public_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_resolved_by_user_id"),
        "trust_safety_investigations",
        ["resolved_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_severity"),
        "trust_safety_investigations",
        ["severity"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_status"),
        "trust_safety_investigations",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_subject_public_id"),
        "trust_safety_investigations",
        ["subject_public_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigations_subject_type"),
        "trust_safety_investigations",
        ["subject_type"],
        unique=False,
    )

    op.create_table(
        "risk_signals",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["investigation_id"], ["trust_safety_investigations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        op.f("ix_risk_signals_created_by_user_id"),
        "risk_signals",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_risk_signals_detected_at"), "risk_signals", ["detected_at"], unique=False
    )
    op.create_index(
        op.f("ix_risk_signals_fingerprint"), "risk_signals", ["fingerprint"], unique=False
    )
    op.create_index(
        op.f("ix_risk_signals_investigation_id"), "risk_signals", ["investigation_id"], unique=False
    )
    op.create_index(op.f("ix_risk_signals_public_id"), "risk_signals", ["public_id"], unique=False)
    op.create_index(
        op.f("ix_risk_signals_resolved_by_user_id"),
        "risk_signals",
        ["resolved_by_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_risk_signals_severity"), "risk_signals", ["severity"], unique=False)
    op.create_index(
        op.f("ix_risk_signals_signal_type"), "risk_signals", ["signal_type"], unique=False
    )
    op.create_index(op.f("ix_risk_signals_source"), "risk_signals", ["source"], unique=False)
    op.create_index(op.f("ix_risk_signals_status"), "risk_signals", ["status"], unique=False)
    op.create_index(
        op.f("ix_risk_signals_subject_public_id"),
        "risk_signals",
        ["subject_public_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_risk_signals_subject_type"), "risk_signals", ["subject_type"], unique=False
    )

    op.create_table(
        "trust_safety_investigation_notes",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["investigation_id"], ["trust_safety_investigations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_notes_author_user_id"),
        "trust_safety_investigation_notes",
        ["author_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_notes_created_at"),
        "trust_safety_investigation_notes",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_notes_investigation_id"),
        "trust_safety_investigation_notes",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_notes_public_id"),
        "trust_safety_investigation_notes",
        ["public_id"],
        unique=False,
    )

    op.create_table(
        "trust_safety_investigation_events",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["investigation_id"], ["trust_safety_investigations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_events_actor_user_id"),
        "trust_safety_investigation_events",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_events_created_at"),
        "trust_safety_investigation_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_events_event_type"),
        "trust_safety_investigation_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_events_investigation_id"),
        "trust_safety_investigation_events",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_safety_investigation_events_public_id"),
        "trust_safety_investigation_events",
        ["public_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_trust_safety_investigation_events_public_id"),
        table_name="trust_safety_investigation_events",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigation_events_investigation_id"),
        table_name="trust_safety_investigation_events",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigation_events_event_type"),
        table_name="trust_safety_investigation_events",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigation_events_created_at"),
        table_name="trust_safety_investigation_events",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigation_events_actor_user_id"),
        table_name="trust_safety_investigation_events",
    )
    op.drop_table("trust_safety_investigation_events")

    op.drop_index(
        op.f("ix_trust_safety_investigation_notes_public_id"),
        table_name="trust_safety_investigation_notes",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigation_notes_investigation_id"),
        table_name="trust_safety_investigation_notes",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigation_notes_created_at"),
        table_name="trust_safety_investigation_notes",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigation_notes_author_user_id"),
        table_name="trust_safety_investigation_notes",
    )
    op.drop_table("trust_safety_investigation_notes")

    op.drop_index(op.f("ix_risk_signals_subject_type"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_subject_public_id"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_status"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_source"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_signal_type"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_severity"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_resolved_by_user_id"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_public_id"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_investigation_id"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_fingerprint"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_detected_at"), table_name="risk_signals")
    op.drop_index(op.f("ix_risk_signals_created_by_user_id"), table_name="risk_signals")
    op.drop_table("risk_signals")

    op.drop_index(
        op.f("ix_trust_safety_investigations_subject_type"),
        table_name="trust_safety_investigations",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigations_subject_public_id"),
        table_name="trust_safety_investigations",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigations_status"), table_name="trust_safety_investigations"
    )
    op.drop_index(
        op.f("ix_trust_safety_investigations_severity"), table_name="trust_safety_investigations"
    )
    op.drop_index(
        op.f("ix_trust_safety_investigations_resolved_by_user_id"),
        table_name="trust_safety_investigations",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigations_public_id"), table_name="trust_safety_investigations"
    )
    op.drop_index(
        op.f("ix_trust_safety_investigations_dismissed_by_user_id"),
        table_name="trust_safety_investigations",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigations_created_by_user_id"),
        table_name="trust_safety_investigations",
    )
    op.drop_index(
        op.f("ix_trust_safety_investigations_assigned_admin_user_id"),
        table_name="trust_safety_investigations",
    )
    op.drop_table("trust_safety_investigations")
